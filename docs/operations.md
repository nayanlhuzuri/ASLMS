# ASLMS v2 — Operations runbook

For the team installing and running the portal on the pilot server and, later, in the State Data Centre.

## 1. What runs

| Service | Role | Public? |
|---|---|---|
| `nginx` | TLS, security headers, rate limit on sign-in, the only open port | yes (80/443) |
| `web` | Next.js portal; proxies `/api/v1` to the API with the user's token held in an httpOnly cookie | no |
| `api` | FastAPI backend | no |
| `worker-ingest` | queue `ingest`: daily cycle (cause lists, cases, scoring) | no |
| `worker-track` | queue `track`: Current Status, weekly refresh, discovery | no |
| `worker-documents` | queue `documents`: order downloads, text extraction, SourceTrace | no |
| `worker-notify` | queue `notify`: e-mail, SMS, digests | no |
| `beat` | scheduler (times in `backend/aslms/jobs/schedules.py`, IST) | no |
| `postgres`, `pgbouncer`, `redis` | database, connection pool, queue broker | no |
| `clamav` | virus scanning of uploads | no |
| `prometheus`, `grafana`, exporters, `flower` | monitoring | Grafana on 127.0.0.1:3001 only |
| `backup` | nightly database dump and document copy at `BACKUP_HOUR` IST | no |

## 2. First installation

```bash
git clone <repo> aslms && cd aslms
cp .env.example .env        # then edit: see §3
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# the one-shot `init` service runs the migrations (directly against postgres) and `aslms bootstrap` (seed, no demo
# data) before the API, workers and scheduler start; it repeats harmlessly on every start
```

The first migration creates the database roles (`docs/DB_STANDARD.md` §8): `aslms_owner` (migrations),
`aslms_app` (the API, workers and CLI; it cannot delete legal records or run DDL) and `aslms_readonly` (Grafana,
reports). Their passwords come from `ASLMS_APP_PASSWORD` and `ASLMS_READONLY_PASSWORD`; `init` and
`make prod-migrate` connect as the owner through `ASLMS_MIGRATE_URL`, everything else as `aslms_app` through
PgBouncer.

The seed creates the code sets (`ref_*`), the designations, Assam and its districts, the State office, the
central monitoring cell, the Advocate General's office, the Gauhati High Court establishment (GAHC01) and one
central-operator account (`SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`). Sign in with it, change the password,
then set up the organisation (§4). Enter the LGD district codes under Administration when the departments
supply them; the portal never guesses an identifier.

Never run `aslms seed-demo` on the pilot or production server; it refuses when `APP_ENV=prod`.

## 3. Settings that must be changed in `.env`

| Variable | Why |
|---|---|
| `APP_ENV=prod` | turns off API docs, refuses demo data, requires the virus scanner |
| `SECRET_KEY` | signs sessions; a long random string, never shared |
| `POSTGRES_PASSWORD`, `ASLMS_APP_PASSWORD`, `ASLMS_READONLY_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`, `SEED_ADMIN_PASSWORD` | defaults are for laptops only; the two role passwords are set by the first migration |
| `PUBLIC_BASE_URL` | the portal's address, used in e-mail links and CORS |
| `SMTP_*` | without `SMTP_HOST`, OTPs and alerts are only written to the log |
| `NAPIX_*` and `NAPIX_ENABLED=true` | see §5; nothing calls NAPIX until `NAPIX_ENABLED` is true |
| `BACKUP_DIR` | a disk that is copied off the server |

Put the TLS certificate and key in `infra/nginx/certs/` and uncomment the 443 server block in `infra/nginx/nginx.conf`.

## 4. Setting up departments

1. **Offices.** Administration → Offices, or in bulk: `aslms import-offices offices.csv` with columns
   `code,name,kind,parent_code` (kinds: department, directorate, section, counsel_office). Parents first.
2. **Users.** Administration → Users & roles (the central operator creates each department's admin; department admins
   create their own users), or `aslms create-user EMAIL "FULL NAME" OFFICE_CODE ROLE`.
3. **Standing counsel codes.** Administration → Department mapping. The "Codes seen in cause lists but not mapped"
   list shows every code found so far, most frequent first. In bulk: `aslms import-codes codes.csv` with columns
   `code,office_code[,weight][,generic]`. Mark `PP, ASSAM` / `GA, ASSAM` style codes as generic: they identify the
   State, not a department.
4. **Name patterns and keywords** per department (e.g. "DIRECTOR OF SECONDARY EDUCATION").
5. After mapping changes, recompute recommendations: Administration → Operations → Rescore, or `aslms rescore`.

## 5. Turning on NAPIX (the live test)

1. Put the credentials in `.env`: `NAPIX_CLIENT_ID`, `NAPIX_CLIENT_SECRET`, `NAPIX_DEPT_ID`, `NAPIX_AUTH_KEY`
   (`NAPIX_AUTH_KEY_MODE` text / hex / base64), then `NAPIX_ENABLED=true`, and restart `api`, workers and `beat`.
2. Run the live test and keep the samples:
   ```bash
   docker compose ... run --rm api aslms napix-check --date YYYY-MM-DD --cnr GAHC01XXXXXXXXXX
   ```
   The first line shows the key fingerprint and the hash self-test. An "encrypted status that NAPIX_AUTH_KEY cannot
   decrypt" means the key or its mode is wrong; `626 INVALID_TOKEN` also points at the key or dept id.
3. Record the answers to the five open points in `docs/claude_ASLMS_design_decisions.md` (is Cause List Details
   complete, est_code per bench, state code, key mode, PDF transport).
4. Load the masters: Administration → Operations → Master sync (bench and case-type masters).

## 6. Daily operation

- **Data collection health:** Reports → Data collection health, or Grafana → ASLMS. The first number to watch is
  "hours since last successful daily cycle" (alert above 14 h).
- **Failures** (a NAPIX error, an unreadable PDF, an order that would not download, a SourceTrace ingestion that kept
  failing) are listed under Administration → Operations with the number of attempts. They are retried by the next
  scheduled run; resolve them there once dealt with.
- **Manual runs:** Administration → Operations → Run job, or `aslms cycle --date YYYY-MM-DD`,
  `aslms refresh status|full|orders|masters|discovery`, `aslms alerts`.
- **Cause-list PDFs already on disk** (e.g. copied from the GHC website): put them in
  `data/causelists/DD-MM-YYYY/` and run `aslms backfill --start ... --end ...`. Re-running is harmless.

## 7. Backups and restore

- The `backup` service writes `BACKUP_DIR/db/aslms-YYYYMMDD-HHMMSS.dump` and `roles-YYYYMMDD-HHMMSS.sql` (the
  three database roles, which a database dump does not contain) every night and copies new document files
  to `BACKUP_DIR/storage/`; files older than `BACKUP_KEEP_DAYS` are removed. Copy `BACKUP_DIR` off the server.
- One backup now: `make backup`.
- Restore (stop `api`, workers and `beat` first, into an empty database): on a fresh server replay the roles
  file first (`psql -d postgres -f /backups/db/roles-....sql`), then
  `docker compose ... run --rm backup /restore.sh /backups/db/aslms-....dump`, copy `storage/` back into the
  storage volume and run `make prod-migrate`.
- Test a restore on a spare machine at least once a quarter.

## 8. Upgrades

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
make backup
make prod-migrate
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
Migrations are forward-only in production; each is tested with upgrade → downgrade → upgrade before release.

## 9. Security notes

- Tokens never reach browser JavaScript: the portal keeps them in httpOnly cookies and adds them server-side.
- Sign-in needs the password and a one-time code sent by e-mail; 5 wrong codes end the attempt; a reused refresh
  token ends all of that user's sessions.
- Visibility is enforced in the database queries for every request, by role and office hierarchy.
- Events, the audit log, the notes trail, custody history and stage history cannot be edited or deleted: the
  database refuses it. Cases, cause lists, documents, orders, requests and every other legal record are never
  deleted either: every foreign key to them is RESTRICT and the application role has no DELETE right on them;
  masters (offices, users, codes, patterns, keywords, watchlist) are deactivated, never removed.
- Every case, request, note, upload, transfer and alert carries a reference number
  (`ASLMS/<office>/<type>/<year>/<serial>`, `docs/DB_STANDARD.md` §3) to quote in correspondence.
- Uploads: PDF, Word and images only, content checked against the extension, size limit, virus scan before storage.
- No case data is sent to any cloud AI service. Court orders and court filings go only to SourceTrace, once enabled.
