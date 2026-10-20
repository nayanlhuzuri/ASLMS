# Design: Pre-pilot hardening (backups, preflight, store, worker liveness, role passwords, PgBouncer)

```
slug: pre-pilot-hardening
status: approved
author: architect
date: 2026-10-20
approved_by: owner (nayanlhuzuri) on 2026-10-20
```

## Context
Backlog row 94 collects the review follow-ups marked "before the pilot" (session of 20 Oct 2026) into one item. The
plan (§8: "Regular database and document backups, and system monitoring through Prometheus and Grafana, will be in
place from the pilot stage"; "PostgreSQL, with PgBouncer for connection pooling") and the approved
`docs/design/deployment-checklist.md` (Parts A, B, C; decisions 3, 12, 13, 16, 24, 29) are the source. Nothing here
is new scope. Each item closes a known hole in work that is already built:

| # | Source | What is wrong today (code read, 20 Oct 2026) |
|---|---|---|
| A | row 86 item 1 | `services/backups.py::dump` holds a REPEATABLE READ transaction open (`pg_export_snapshot()`) while `pg_dump --snapshot` runs. That session is *idle in transaction*, and Postgres runs with `idle_in_transaction_session_timeout=15min` (`compose.yml`). A dump longer than 15 minutes therefore has its exporting session killed. Every backup then fails, and so does `aslms ops migrate`, which needs its `pre-migrate` backup first. The dev dump is already 352 MB. |
| B | row 86 item 5 | `Settings.app_env` is any string; `is_prod` is `app_env == "prod"`. So `APP_ENV=production` or `Prod` silently turns every preflight rule into a warning and `refuse_superuser` off. |
| C | row 86 item 9 | A document store created before the uid-10001 hardening is owned by root (mode 755). Every order-PDF store fails with `PermissionError`: 521 items in one window on 19 Oct. `init` does not mount `./data` and checks nothing. Only the runbook (section 5) has the fix. |
| D | row 88 item 1 | `WorkerStalled` uses `aslms_worker_last_pass_timestamp`, which is the *start* of the latest `queue-run` pass. A load pass runs until the queue is empty (`max_items=None`), often for hours. So the alert fires after 2 hours while the worker is busy claiming rows. |
| E | row 81 | `cli/db.py::_set_password` sends `ALTER ROLE … LOGIN PASSWORD '<plain text>'`. `SET LOCAL log_statement = 'none'` keeps it out of the statement log. But the plain text still reaches the server, and from there `pg_stat_activity`, error logs (a failed statement is logged with its text under `log_min_error_statement`) and any extension that records statements. |
| F | row 93 | `infra/pgbouncer/Dockerfile` installs `'pgbouncer>=1.21'`, so it is not pinned. The image has 1.25.1-r0 today. psycopg's documentation names PgBouncer 1.22 as the minimum for prepared statements in transaction mode. |
| G | row 90 | Transaction pooling with protocol-level prepared statements needs psycopg 3.2+ on libpq 17+. Only then does psycopg close prepared statements with the protocol message `Close` (which PgBouncer tracks) rather than the SQL `DEALLOCATE` (which it does not). Nothing checks libpq. The image has psycopg 3.3.6 on libpq 18.6 today (`docker exec aslms-api-1`). |
| H | row 92 | The `pgbouncer` healthcheck is `nc -z 127.0.0.1 6432`: only the open port. A wrong `aslms_app` password or an unreachable Postgres still shows "healthy", and `api`, `worker` and `scheduler` start against a pool that cannot log in. |
| I | row 91 | `test_pgbouncer.py`'s session-feature scan is line-based and anchored at the start of a line, a quote, `;` or `(`. It misses an indented `SET` inside a triple-quoted SQL string, and `SET TIME ZONE`, `RESET`, `DISCARD` and SQL `PREPARE`. |

Rows 81, 90, 91, 92 and 93 are built here in full. Row 86 items 1, 5 and 9 and row 88 item 1 are built here; the
other items of rows 86 and 88 stay in those rows.

Not covered: the other items of rows 86 (2, 3, 4, 6, 7, 8) and 88 (2 to 5); running migrations as a non-superuser
`aslms_owner` (row 80); the owner-run checks (rows 85, 87, 89).

No table, column, reference code, migration, endpoint, permission or audit action is added. These are deployment
steps (as in deployment-checklist decision 12: role passwords are set without an audit row).

## Decisions

1. **(A) The exporting transaction turns off its own idle timeout.** The first statement inside `dump()`'s
   REPEATABLE READ transaction, before `pg_export_snapshot()`, is
   `SET LOCAL idle_in_transaction_session_timeout = 0`. It is transaction-scoped, so it ends with the transaction
   and the server-wide 15-minute guard stays for every other session. `pg_dump` already sets the same thing for its
   own session. Alternatives: raise the server setting (this weakens the guard for the application); a per-role
   setting on the owner (it would also cover `init` and `migrate` sessions that should keep the guard); a session
   `SET` (it outlives the transaction on a pooled connection; the dump connects directly, but the narrower scope is
   still right). The backup's other connections (`pg_dumpall`, `pg_restore --list`) hold no open transaction and
   are unchanged. `restore_check` and `restore` do not hold an idle transaction around a client tool (checked in
   `backups.py`: they run `pg_restore` with no open transaction of their own), so they are unchanged.

2. **(B) `APP_ENV` is one of `dev`, `test`, `prod`, checked when the settings load, and preflight reports it by
   name.** `Settings.app_env` becomes `Literal["dev", "test", "prod"]`, with exact lower case and no aliases.
   `production`, `Prod` and empty are all refused. Every process loads `Settings`, so `api`, `worker`, `scheduler`,
   `backup`, the exporters and every CLI command all stop on an unknown value. None of them can run with the checks
   silently off. `aslms ops preflight` catches the settings error for `app_env` and prints
   `preflight error: APP_ENV: must be dev, test or prod` (the variable and the rule, never other values) and exits
   1. Since preflight runs first in `init` and `migrate`, nothing else starts. Alternative: a preflight-only rule.
   That does what the backlog line says, but a process started outside Compose (`aslms queue-worker` by hand) would
   still read `production` as "not prod" and skip `refuse_superuser`, so refusing at load is the stronger reading of
   the same rule. Preflight gains a third finding level, `fatal`, used by decisions 2 and 6. A fatal finding stops
   the start at every `APP_ENV`; `error` stays prod-only and `warning` stays a warning.

3. **(C) `init` checks that the document store is writable by its own user (uid 10001) and says what to run.**
   - **New command `aslms ops store-check`**, backed by service `services/store_check.py`. It runs in `init` right
     after preflight: `aslms ops preflight && aslms ops store-check && aslms ops db-guard && aslms db-roles && aslms seed`.
   - **`init` mounts `./data:/data`** (read-write), like `api`, `worker` and `scheduler`.
   - **The check works on `STORAGE_DIR`** (`/data/store`), the only folder the application writes. The cause-list
     folder is only read, and every write goes through `LocalStore.put` into `<sha[:2]>/`.
   - **What it does:** if the store is missing, it creates it (this fails when `/data` itself is root-owned, as on a
     fresh Linux host where Docker created `./data`). It then makes a real write probe (create and remove a file
     `.aslms-write-check-<random>`) in the store root and in every first-level folder. There are at most 256, and an
     `os.access` answer is not trusted on Docker Desktop bind mounts.
   - **On failure** it exits 1 at every `APP_ENV` and prints:
     - how many folders failed, and the first one;
     - the two remedies from the runbook. On a Linux host: `sudo chown -R 10001:10001 ./data/store`. On Docker
       Desktop for Windows, where `chown` is refused, the command that worked on 19 Oct: `docker compose run --rm
       --no-deps -u root --entrypoint sh worker -c "chmod -R a+rwX /data/store"`;
     - a pointer to `docs/operations.md` section 6.
   - **On success** it prints the store path and the folder count.
   - **The runbook** paragraph moves from section 5 into section 6 (Upgrading), with only `/data/store` named;
     section 3 step 4 is unchanged.

   Alternatives considered:
   - Let `init` chown the store as root. Refused: `init` runs as uid 10001 with `cap_drop: ALL`, and chown is
     refused on Windows bind mounts anyway.
   - A warning only. Refused: on 19 Oct the failure was silent for a whole window.
   - A full recursive walk of the files. Not needed: files are written once through a temporary name and a rename,
     so only folder write access matters.

4. **(D) Worker liveness is "the later of the latest pass start and the latest row the worker claimed".** The ops
   exporter adds the gauge `aslms_worker_alive_timestamp` = `greatest(max(job_runs.started_at) for job queue-run,
   max(fetch_queue.started_at) for kinds not in queue.LOCAL_KINDS)`. `queue.claim` sets `started_at = now()` on
   every claim. `search_rows` rows (`LOCAL_KINDS`) are claimed by the scheduler's Celery task, so they are excluded:
   otherwise a live scheduler would hide a dead worker.
   - `WorkerStalled` becomes `(time() - aslms_worker_alive_timestamp > 7200) and on()
     (max(aslms_queue_oldest_pending_seconds) > 0)` with `for: 5m`, unchanged otherwise. Its summary becomes "no
     queue worker activity for 2 hours while the queue has runnable rows".
   - `aslms_worker_last_pass_timestamp` stays, for the dashboards' "last pass" figure. The two dashboard panels that
     show `time() - aslms_worker_last_pass_timestamp` as liveness switch to the new gauge.
   - Cost: a sequential scan of `fetch_queue`, measured at 22 ms for 357,769 rows on the dev database. It runs inside
     the exporter's statement timeout, so no index or migration is needed.

   Alternatives considered:
   - A heartbeat column on `job_runs` written during the pass. Rejected: it needs a migration and a write on every
     item, and gives the same signal as the claim time that already exists.
   - A shorter pass (`--max-items`). Rejected: it changes the worker's behaviour to suit an alert.
   - `napix_call_log.called_at`. Rejected: there are no calls while the switch is off or the window is spent, so it
     would raise false alarms.

   A single row hanging for more than 2 hours still fires the alert, which is correct.

5. **(E) Role passwords are sent as a client-side SCRAM-SHA-256 verifier.** `_set_password` computes the verifier
   with libpq's `PQencryptPasswordConn` through psycopg
   (`conn.pgconn.encrypt_password(password, role, b"scram-sha-256")`, on the owner connection it already opens). It
   then sends `ALTER ROLE <role> LOGIN PASSWORD '<SCRAM-SHA-256$…>'`, quoted by `psycopg.sql.Literal`.
   - The algorithm is named explicitly, never taken from the server's `password_encryption`, so an md5 setting
     cannot weaken it.
   - `SET LOCAL log_statement = 'none'` stays as defence in depth, because the verifier is still sensitive offline.
   - The statement is built by a small function `role_password_statement(pgconn, role, password)` so that tests
     can inspect it.
   - Error messages still name only the exception class.
   - PgBouncer is unaffected: its user list keeps the plain text from `.env`, which it needs for SCRAM to the server.

   Alternative: compute SCRAM in Python (PBKDF2 and HMAC by hand). Rejected: libpq's function is the reference
   implementation (the one `psql \password` uses) and follows the server's `scram_iterations`.

6. **(G) The libpq floor is checked at start-up and in the tests.**
   - **Start-up:** `preflight.check` adds a **fatal** finding (`libpq: version N is older than 17; PgBouncer
     transaction pooling with prepared statements needs libpq 17 or later — rebuild the image`) when
     `psycopg.pq.version() < 170000`. It is fatal at every `APP_ENV` because `api`, `worker` and `scheduler` always
     go through PgBouncer and they share the image `init` runs in. It is a build defect, not a setting.
   - **Tests:** a unit test asserts the floor in the test environment, and the preflight test covers the finding
     with a patched version.
   - `pyproject.toml` already requires `psycopg[binary]>=3.2`. The binary wheel brings its own libpq (18.6 today),
     so the check guards against a future switch to a system libpq.

   Alternative: a test-only check. Rejected: the tests run in the developer's virtual environment, not in the image
   that serves the pilot.

7. **(F) PgBouncer is pinned exactly.** The Dockerfile has `apk add --no-cache 'pgbouncer=1.25.1-r0'`, the version
   Alpine 3.23 has today (`apk policy pgbouncer` on `alpine:3.23.3`, 20 Oct 2026). `alpine:3.23.3` is already
   pinned.
   - The test parses the pin and requires version 1.22 or later. The comments in the Dockerfile and `compose.yml`
     now say 1.22+ (psycopg's documented minimum), not 1.21+.
   - When Alpine republishes the package (`-r1`), the build fails loudly and someone changes the pin on purpose,
     which is the point of pinning. The pilot gets images through `docker save` / `docker load` (runbook section
     8), so a built image does not depend on the mirror.

   Alternative: the fuzzy pin `~1.25`. Rejected: it is not reproducible.

8. **(H) The PgBouncer healthcheck logs in as `aslms_app` and runs `SELECT 1` through the pool.**
   - **The image** gains `postgresql16-client=16.15-r0`. It brings psql; its major version matches the server
     (16.15).
   - **The script** is `infra/pgbouncer/healthcheck.sh` (LF line endings, copied to
     `/usr/local/bin/pgbouncer-healthcheck.sh`, mode 0755). It runs `psql -X -A -t -h 127.0.0.1 -p 6432 -U
     aslms_app -d "${POSTGRES_DB:-aslms}" -c 'SELECT 1'` with `PGCONNECT_TIMEOUT=3`, and passes only when the
     output is `1`.
   - **The password** reaches psql only as `PGPASSWORD`, taken inside the script from the container's existing
     `ASLMS_APP_PASSWORD`. It is never on a command line, never in `compose.yml` (no Compose interpolation into the
     healthcheck, which `docker inspect` would show), and never echoed. psql's error line (for example "password
     authentication failed for user aslms_app") stays in the health log, because it carries no secret.
   - **Compose:** `test: ["CMD", "/bin/sh", "/usr/local/bin/pgbouncer-healthcheck.sh"]`, interval 5 s, timeout
     5 s, retries 20, plus `start_period: 10s`.
   - It logs in through PgBouncer to Postgres, so "healthy" now means "the application can log in". The HBA line
     `host $DB aslms_app 0.0.0.0/0 scram-sha-256` already admits 127.0.0.1.
   - The probe's `aslms_app` session lives in the pool. `migrate` and `restore` already stop `pgbouncer` first, so
     `db_guard.count_app_sessions` is unaffected.

   Alternatives considered:
   - `pg_isready`. Rejected: it does not authenticate.
   - A `.pgpass` file written by the entrypoint. Rejected: it adds a second copy of the secret on the tmpfs for no
     gain.

9. **(I) The session-feature scan reads SQL statements, not lines.** The scan in `test_pgbouncer.py` becomes two
   parts:
   - **Anywhere-in-the-line patterns, unchanged and line-based:** session advisory locks, temporary tables,
     `set_config(…, false)` and `WITH HOLD`. They are unambiguous, and the line scan also catches SQLAlchemy
     `func.pg_advisory_lock(…)`, which is not a string.
   - **Statement-start patterns, AST-based:** each module of `backend/aslms` is parsed with `ast`. Every string
     constant except docstrings is collected, and f-strings are joined with `{}` for each placeholder. Each string
     is split on `;`. Leading whitespace, newlines, `(`, `--` comment lines and `/* */` comments are stripped. The
     statement is flagged when it starts with:
     - `SET` not followed by `LOCAL`, `TRANSACTION` or `CONSTRAINTS` (all transaction-scoped), with an optional
       `SESSION` and then `ROLE`, `AUTHORIZATION`, `TIME ZONE`, `NAMES`, `SCHEMA` or `<name> =` / `<name> TO`. This
       covers indented `SET` in a triple-quoted string and `SET TIME ZONE`.
     - `RESET ALL | ROLE | SESSION AUTHORIZATION | <name>` (the whole statement).
     - `DISCARD ALL | PLANS | SEQUENCES | TEMP | TEMPORARY`.
     - `PREPARE <name> [(types)] AS` or `PREPARE TRANSACTION`.
     - `DEALLOCATE [PREPARE] ALL | <name>`. This is added because it is the other half of SQL-level prepared
       statements and is just as invisible to PgBouncer.
     - `LISTEN` / `UNLISTEN`, moved here from the line scan.
   - **An `UPDATE … SET` is never flagged**, because its `SET` is not at a statement start. This is why the scan
     cannot simply allow indentation at the start of a line.
   - **Case of the keywords:**
     - In a string passed directly as the first argument of `text(…)`, `.execute(…)`, `.exec_driver_sql(…)` or
       `sql.SQL(…)`, keywords match in any case.
     - In every other string, keywords match in upper case only. This follows the package's convention: there is
       no lower-case SQL statement in `backend/aslms`.
     - The reason: a trial run of the case-insensitive rule over the package on 20 Oct 2026 flagged two English
       strings (`'Reset passwords'` in `access_seed.py`, `'set names the incoming head only'` in `tickets.py`). The
       upper-case rule flagged nothing.
   - **Reports** keep the form `path:line: name`, where line is the string's first line.

   Alternatives considered:
   - Allow leading whitespace in the line regex. Rejected: every multi-line `UPDATE … SET` would be flagged.
   - A real SQL parser (sqlglot or pglast). Rejected: it adds a test dependency for six keywords.

## Data
None. No table, column, reference code or migration. `docs/schema/schema.md` is unchanged.

The exporter reads `fetch_queue.started_at` and `fetch_queue.kind` as `aslms_readonly`, which already holds SELECT
on `fetch_queue` (it reads the queue gauges today). The SCRAM change touches only the role catalogue
(`pg_authid.rolpassword` of `aslms_app` and `aslms_readonly`). It does so through the existing `aslms db-roles`
step, which re-sets both passwords at every `init`, so the first start after this change replaces the stored
verifiers.

## Services

- **`services/backups.py`**
  - `dump()`: one added statement, `conn.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))`, as
    the first statement inside the REPEATABLE READ `conn.begin()` block, with a comment naming decision 1. Nothing
    else changes; the snapshot is exported after it and shared as before.
- **`core/config.py`**
  - `app_env: Literal["dev", "test", "prod"] = "dev"`.
  - `is_prod` is unchanged.
- **`services/preflight.py`**
  - New level `FATAL = "fatal"`, and new finding `libpq_floor()` (returns a fatal `Finding("libpq", …)` when
    `psycopg.pq.version() < LIBPQ_MIN = 170000`). The version is injectable for tests:
    `libpq_floor(version: int | None = None)`.
  - `check()` appends it.
  - `raise_on_errors(findings, is_prod)` raises with every fatal finding, plus the errors when `is_prod`.
  - `errors()` includes fatal findings.
  - The module docstring lists the two fatal rules.
- **`cli/ops.py`**
  - `preflight_cmd` wraps `get_settings()`. A pydantic `ValidationError` whose failing field is `app_env` prints
    `preflight fatal: APP_ENV: must be dev, test or prod` and exits 1. Any other settings error is re-raised as
    today.
  - Fatal findings print in red like errors.
  - New command `store-check`, which calls `store_check.check(settings.storage_dir)`, prints the result and exits 1
    on failure.
  - The module docstring lists `store-check`.
- **`services/store_check.py`** (new)
  - `StoreCheck` dataclass: `root`, `folders_checked`, `failed: list[str]`, `created: bool`, `ok` property.
  - `check(root, *, probe=write_probe) -> StoreCheck`.
    - `mkdir(parents=True, exist_ok=True)`. A `PermissionError` on mkdir counts as the root failing.
    - Then the probe on the root and on each first-level directory, sorted.
    - It never follows symlinks out of the root and never touches the files.
  - `write_probe(folder)`: create and remove `.aslms-write-check-<token_hex(8)>` with `os.open(O_CREAT|O_EXCL|O_WRONLY)`.
  - `remedy_lines() -> list[str]`: the two commands and the runbook pointer (decision 3), one source for the CLI and
    the tests.
- **`cli/db.py`**
  - `role_password_statement(pgconn, role, password) -> psycopg.sql.Composed`, which builds the statement with the
    verifier from `pgconn.encrypt_password(password.encode(), role.encode(), b"scram-sha-256")`.
  - `_set_password` gets `raw.driver_connection.pgconn` and executes that statement after
    `SET LOCAL log_statement = 'none'`.
  - The docstrings say "a SCRAM-SHA-256 verifier computed on the client; the plain text never leaves the process".
- **`services/ops_metrics.py`**
  - In `collect_database`, one more scalar read: `select(func.max(FetchQueueItem.started_at)).where(FetchQueueItem.kind.not_in(queue.LOCAL_KINDS))`.
  - The new sample is `aslms_worker_alive_timestamp` = the later of that value and `last_pass` (0 when both are
    missing).
  - New `HELP` entry: "the queue worker's liveness: the later of the latest queue-run pass start and the latest row
    it claimed (0: never)". The `aslms_worker_last_pass_timestamp` help drops "the queue worker's liveness".
- **Infrastructure**
  - **`infra/pgbouncer/Dockerfile`:**
    - `apk add --no-cache 'pgbouncer=1.25.1-r0' 'postgresql16-client=16.15-r0'`.
    - `COPY healthcheck.sh /usr/local/bin/pgbouncer-healthcheck.sh` with mode 0755.
    - The comment now says 1.22+.
  - **`infra/pgbouncer/healthcheck.sh`** (new): decision 8. It starts with `set -eu` and requires
    `ASLMS_APP_PASSWORD` (`: "${ASLMS_APP_PASSWORD:?}"` with no message that could echo it). It writes nothing to
    disk.
  - **`compose.yml`:**
    - The `pgbouncer` healthcheck uses the script and gets `start_period: 10s`.
    - `init` gets `volumes: [./data:/data]` and the `store-check` step in its command.
    - The `init` and `pgbouncer` comments are updated (1.22+).
  - **`infra/prometheus/rules.yml`:** `WorkerStalled` as in decision 4.
  - **`infra/prometheus/rules.test.yml`:** cases for decision 4 (see Tests).
  - **`infra/grafana/dashboards/aslms-overview.json` and `aslms-redis-celery.json`:** the liveness panels use
    `time() - aslms_worker_alive_timestamp`, titled "worker last activity".
- **Docs**
  - **`docs/operations.md`:**
    - Section 5: the uid-10001 paragraph moves to section 6 with the `store-check` message.
    - Section 17: WorkerStalled is described as "no queue worker activity (pass start or claimed row) for 2 hours".
    - Section 18: the pinned version, the login healthcheck and the libpq floor.
    - Section 4: `db-roles` sends a SCRAM verifier.
  - **`.env.example`:** the `APP_ENV` comment says "dev, test or prod; anything else stops every service".
  - **`docs/claude_ASLMS_design_decisions.md`:** a new dated section in the same change.

No audit rows. Every change is a deployment step or a monitoring reading. None calls NAPIX or SourceTrace, and none
touches visibility, case data or uploads.

## API
None. No endpoint changes; no `Permission` is added or required.

## Jobs
None added. The ops exporter's reading gains one query (decision 4). The `backup` service's schedule and retention
are unchanged; only the exporting transaction changes (decision 1). The worker and the queue are unchanged.

## Tests

Unit (`backend/tests/unit/`):
- `test_preflight.py`
  - `test_unknown_app_env_is_refused_by_settings`: `Settings(_env_file=None, app_env=v)` raises for `production`,
    `Prod`, `""` and `staging`, and loads for `dev`, `test` and `prod`.
  - `test_preflight_cli_names_app_env_and_exits_1`: monkeypatched `get_settings` raising the `app_env` validation
    error. Output has `APP_ENV: must be dev, test or prod`, exit code 1, and no other variable's value.
  - `test_libpq_floor_is_fatal_at_every_app_env`: `libpq_floor(160004)` is fatal, and `raise_on_errors` raises with
    `is_prod=False` and with `True`. `libpq_floor(170000)` is `None`.
  - `test_errors_stay_prod_only_and_fatal_does_not`: an error finding with `is_prod=False` does not raise; a fatal
    one does.
- `test_pgbouncer.py`
  - `test_libpq_is_17_or_later`: `psycopg.pq.version() >= 170000` in the test environment.
  - `test_session_feature_scanner_flags_what_it_should`, rewritten for decision 9.
    - **Flagged:** an indented `SET statement_timeout = 0` in a triple-quoted `text("""…""")`; `"SET TIME ZONE
      'UTC'"`; `"SET SESSION TIME ZONE 'UTC'"`; `"RESET ALL"`; `"RESET statement_timeout"`; `"RESET ROLE"`;
      `"DISCARD ALL"`; `"DISCARD PLANS"`; `"PREPARE q (int) AS SELECT $1"`; `"PREPARE TRANSACTION 'x'"`;
      `"DEALLOCATE ALL"`; `"DEALLOCATE PREPARE q"`; `"SELECT 1; SET search_path TO x"`; `"-- note\nSET x = 1"`;
      `text("set search_path to x")` (lower case in a direct `text()` argument); `f"SET {name} = {value}"`; plus
      every sample flagged today.
    - **Allowed:** a multi-line `UPDATE job_runs\n   SET status = 'failed'\n WHERE …`; `"SET TRANSACTION READ
      ONLY"`; `"SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"`; `"SET CONSTRAINTS ALL DEFERRED"`;
      `text(f"SET LOCAL statement_timeout = {ms}")`; a docstring containing `SET search_path TO x`;
      `"Reset passwords"`; `"set names the incoming head only"`; `"reset overdue: probing in 5 s"`; plus every
      sample allowed today.
  - `test_no_session_level_postgres_features`: both parts over `backend/aslms`, with more than 50 files read. It
    passes on the current package.
  - `test_pgbouncer_image`: the exact pin `pgbouncer=X.Y.Z-rN` is present and parsed as ≥ 1.22.0;
    `postgresql16-client=` is pinned; the healthcheck script is copied; `USER 10001` and pinned Alpine as before.
    The `'pgbouncer>=1.21'` assertion is removed.
  - `test_pgbouncer_healthcheck_logs_in_as_app`, covering the script:
    - LF line endings;
    - `-U aslms_app`, `-h 127.0.0.1`, `-p 6432` and `SELECT 1`;
    - the password only as `PGPASSWORD="$ASLMS_APP_PASSWORD"`, with no `password=` in a conninfo and no `echo` or
      `printf` of the variable.
    - In `compose.yml`: the healthcheck test is `["CMD", "/bin/sh", "/usr/local/bin/pgbouncer-healthcheck.sh"]`,
      and the healthcheck holds no `$`.
  - `test_compose_pgbouncer_service`: the `"6432" in healthcheck` assertion is replaced by the script assertion.
- `test_store_check.py` (new)
  - `test_writable_store_passes_and_counts_folders`: tmp store with three `ab/` folders; real probe; `ok`; three
    folders; no probe file left.
  - `test_missing_store_is_created`.
  - `test_unwritable_folders_are_reported`: a fake probe raising `PermissionError` for two folders. `failed` names
    both; `ok` is False.
  - `test_unwritable_root_is_reported_when_mkdir_fails`: a patched mkdir raises `PermissionError`.
  - `test_real_permission_denied_on_posix`: chmod 0o555 on a folder, skipped on Windows and as root.
  - `test_cli_store_check_exits_1_with_both_remedies`: output has `chown -R 10001:10001`, `chmod -R a+rwX` and
    `docs/operations.md section 6`; exit 1. It exits 0 on a writable store.
- `test_deployment_compose.py`
  - `test_compose_init_guards_instead_of_migrating`: the init command holds `ops store-check` after
    `ops preflight` and before `ops db-guard`.
  - `init` mounts `./data:/data`.
- `test_db_roles_command.py`: unchanged (it patches `_set_password`). Add
  `test_set_password_sends_a_verifier_not_the_text`: a fake raw connection records the executed statements. Its
  `pgconn.encrypt_password` returns `b"SCRAM-SHA-256$4096:fake"`. The statement text holds the verifier and not the
  password, and `SET LOCAL log_statement = 'none'` comes first.
- `test_ops_metrics_unit.py`: `aslms_worker_alive_timestamp` is in `HELP`.
- `infra/prometheus/rules.test.yml` (run with `promtool test rules`):
  - an old pass start (`-10000`) with a recent alive timestamp and runnable rows: no WorkerStalled;
  - an old alive timestamp with runnable rows: WorkerStalled at 6 minutes, with the new summary;
  - an old alive timestamp with nothing runnable: none.
  - The three existing cases are rewritten on `aslms_worker_alive_timestamp`.

Database (`backend/tests/db/`):
- `test_deployment_ops.py`
  - `test_dump_survives_a_pg_dump_longer_than_the_idle_timeout`. The test URL carries
    `options=-c idle_in_transaction_session_timeout=1000`. `backups._tool` is patched: for `pg_dump` it sleeps 2 s
    and writes the part file; the other tools write their files and answer. `dump()` returns a manifest. Without
    decision 1 the commit fails, because the server ends the session.
  - `test_role_password_is_stored_as_scram_and_logs_in`. The test creates a scratch role
    `aslms_pwcheck_<hex>` with LOGIN, calls `_set_password(TEST_URL, role, pw)`, and checks that
    `pg_authid.rolpassword` starts with `SCRAM-SHA-256$`. Connecting as the role with `pw` succeeds and with a wrong
    password fails. `role_password_statement(...).as_string(conn)` does not contain `pw`. The role is dropped in a
    finaliser.
- `test_ops_metrics.py`
  - `test_worker_alive_is_the_later_of_pass_start_and_claim`: a `queue-run` row started 3 h ago and a fetch_queue
    row of kind `causelist_day` claimed 1 min ago, so alive is about now − 1 min while `last_pass` stays at
    −3 h.
  - `test_search_rows_claims_do_not_count_as_worker_activity`: only a recent `search_rows` claim, so alive equals
    the pass start.
  - `aslms_worker_alive_timestamp` is added to the expected names list.

Full suite: `ruff check` clean; `pytest -q` green.

## Verification
The integrator, on the dev Compose stack (`NAPIX_ENABLED` untouched):

1. `docker compose build init api worker scheduler pgbouncer backup ops-exporter`, then `docker compose up -d`.
   - `docker compose logs init` shows `preflight passed`, then `store-check: /data/store writable (N folders)`
     (N about 256 on the dev store), then db-guard at head, `aslms_app password set` and the seed.
   - `docker compose exec postgres psql -U aslms -d aslms -Atc "select rolname, left(rolpassword, 14) from
     pg_authid where rolname in ('aslms_app','aslms_readonly')"` shows `SCRAM-SHA-256$` for both.
2. `docker compose ps pgbouncer` shows healthy. `docker inspect --format '{{json .State.Health.Log}}' aslms-pgbouncer-1`
   shows output `1` and no password. In a scratch project with a wrong `ASLMS_APP_PASSWORD` in PgBouncer's
   environment only, the service turns unhealthy with "password authentication failed".
   `docker compose exec pgbouncer pgbouncer --version` shows `PgBouncer 1.25.1`.
3. `docker compose exec api python -c "import psycopg; print(psycopg.pq.version())"` prints 180006 or higher.
4. `APP_ENV=production docker compose run --rm --no-deps init aslms ops preflight` prints
   `APP_ENV: must be dev, test or prod` and exits 1.
5. Store check:
   - In a scratch copy, `docker compose run --rm --no-deps -u root --entrypoint sh init -c "mkdir -p /data/store/zz
     && chmod 755 /data/store/zz"` makes a root-owned folder. `docker compose run --rm --no-deps init aslms ops
     store-check` then exits 1, naming `zz` and both remedies.
   - Remove the folder afterwards, as root, in the same scratch copy.
6. `docker compose exec backup aslms ops backup --tag pre-pilot-check` completes. The `idle_in_transaction` change
   is proved by the database test. On the pilot machine the first real backup is the owner's check (row 85).
7. During the running historical load:
   - `docker compose exec ops-exporter aslms ops metrics --once | grep worker_` shows `aslms_worker_alive_timestamp`
     within the last minute while `aslms_worker_last_pass_timestamp` is older. Prometheus shows no WorkerStalled.
   - `promtool check rules` and `promtool test rules infra/prometheus/rules.test.yml` pass.
8. `cd backend && ruff check && pytest -q`: green, with the counts recorded in the report.

## Open questions
None.

## Deviations
Made while building (developer, 20 Oct 2026); none changes a business rule, a table or an API field.

1. **`init` gets `STORAGE_DIR: /data/store`** in its environment as well as the `./data:/data` mount. The design names
   only the mount, but without the variable `init` reads the settings default `data/store` (relative to `/app`) and
   would check the wrong folder. `api`, `worker` and `scheduler` already set it the same way.
2. **The preflight message for an unknown `APP_ENV` is `preflight fatal: APP_ENV: must be dev, test or prod`**, as in
   the Services section; decision 2's text says `preflight error:`. The tests check only
   `APP_ENV: must be dev, test or prod` and exit 1.
3. **`store_check.check` reports `PermissionError` (and `EACCES`, `EPERM`, `EROFS`) as an unwritable folder; any other
   `OSError` (a full disk, for example) is raised**, so `init` still exits non-zero with the real cause instead of the
   chown remedy. `failed` holds full paths, so the message names the folder (for example `/data/store/zz`).
4. **`infra/pgbouncer/entrypoint.sh`**: the comment in the generated `pgbouncer.ini` now says 1.22+ like the Dockerfile
   and `compose.yml` (comment only).
5. **Runbook section 3, step 2** also says that `APP_ENV` must be exactly `prod` (anything else stops every service),
   next to the `.env.example` comment of the design.
6. **Tests beyond the list**: `test_preflight_cli_reraises_other_settings_errors`, `test_preflight_check_reports_an_old_libpq`,
   `test_other_os_errors_are_not_hidden`, `test_symlinks_are_not_followed` (skipped where symbolic links are not
   available), `test_cli_store_check_passes_on_a_writable_store`, `test_role_password_statement_quotes_the_verifier`,
   `test_worker_alive_without_a_pass_reads_the_claim_or_zero`, a `promtool` case for a long pass with recent claims,
   and scanner samples for `/* */` comments, `sql.SQL("reset all")`, `exec_driver_sql("listen x")` and
   `func.pg_advisory_lock(42)`. The dump test first proves that the server enforces the 1-second timeout on its URL.
7. **The unknown-`APP_ENV` line also comes from the root `aslms` callback** (review fix). The callback configures
   logging, which loads the settings before any command runs, so `aslms ops preflight` never reached its own handler.
   The callback now catches the same `ValidationError` and prints the same line, `preflight fatal: APP_ENV: must be
   dev, test or prod`, with exit 1, for every `aslms` command (so `init`, `migrate` and `backup` stop the same way);
   any other settings error is still raised. The check is shared as `config.is_app_env_error` and the line as
   `config.APP_ENV_FATAL`. `test_unknown_app_env_through_the_real_entry_point` sets `APP_ENV=production` in the
   environment, clears the `get_settings` cache and invokes the main app with nothing patched.
