# Design: GitHub remote and CI (gates on every push, a test database per run, secret scanning)

```
slug: github-and-ci
status: approved
author: architect
date: 2026-10-20
approved_by: owner (nayanlhuzuri) on 2026-10-20
```

> **Owner's decisions at approval (20 Oct 2026):** approved with the recommended defaults, except that the repository **always** stays on the owner's personal account `nayanlhuzuri` (no later transfer to an organisation). Accepted: a private repository; the GitHub Free plan to start; the integrator pushes `main` and the `feature/*-done` tags after each local merge (fast-forward only, never forced), which replaces the 4 Oct "never push" rule; the owner signs in `gh` on the cycle machine and makes the first push after the two full-history scans.


## Context
Backlog row 15: "Git remote, GitHub Actions running `ruff` and `pytest` against a Postgres service, so cycles can be
verified outside a Claude Code session." The plan says nothing about source control or CI (checked with
`docx_text.py --grep` for GitHub, repository, CI/CD). So this item changes only how the code is kept, checked and
shared. No plan rule changes.

What is in place (main at 700a7d6, 20 Oct 2026):
- No git remote. Every cycle is squash-merged into a local `main` by the integrator and tagged
  `feature/<slug>-done` (32 tags). The team's rule is "never push" (decisions log, "The agent team", 4 Oct 2026;
  `.claude/agents/integrator.md`; `.claude/skills/team-cycle/SKILL.md`). `git push` is in the `ask` list of
  `.claude/settings.json`. The team README says: "There is no server-side scheduler yet: that needs a git remote
  and CI."
- The gates in `docs/team/definition-of-done.md` run only on the owner's Windows machine:
  - `ruff check` and `ruff format`;
  - `pytest -q`: 1318 tests, 947 s on 18 Oct. The database tests use the Compose Postgres;
  - in `frontend/`: `npm run lint`, `typecheck`, `test`, `build`, and `gen:api` with no diff;
  - `docker compose build`;
  - `backend/tools/portal_smoke.py` against the running `web` service;
  - `promtool test rules` (operations.md section 17).
- Database tests (`backend/tests/db/conftest.py`) all use one database: the one named by
  `ASLMS_TEST_DATABASE_URL` (default `postgresql+psycopg://aslms:aslms@127.0.0.1:5433/aslms_test`). The `migrated`
  fixture wipes it, downgrades to base and upgrades to head. The `clean_db` and `world` fixtures wipe it again with
  committed transactions. Two sessions at once therefore destroy each other's data. This happened in the
  independent audit (Area 3: "for CI use a database per run") and in the search-court-advocate-filing report
  ("two pytest runs overlapped on the shared `aslms_test` database"). Seventeen modules import the module constant
  `TEST_URL` directly. The database tests are skipped when the server cannot be reached, so a CI job without a
  database would pass without running them.
- The migrations also change cluster-wide state:
  - 0001 creates the roles `aslms_owner`, `aslms_app` and `aslms_readonly`;
  - 0001 sets their passwords, if `.env` names them;
  - 0020 grants `pg_monitor` to `aslms_readonly`, and its downgrade revokes it.

  Roles are shared by every database on the server. A separate database per run does not isolate them.
- `.gitignore` already excludes these: `.env` and `.env.*` (but not `.env.example`); `*.pem`; `*.key`; `data/`;
  `backups/`; `infra/proxy/certs/`; `infra/clamav/freshclam.conf`; `docs/specs/napix/hc/samples/`;
  `.claude/settings.local.json`; `.claude/worktrees/`.

**What I found when checking the repository for anything that must not be pushed** (20 Oct 2026, read-only):
- **Credentials: none found.**
  - No tracked file, and no file in any commit's history, is a `.env`, a key, a certificate or a dump. The only
    `.env*` files ever added are `.env.example` and `frontend/.env.example`.
  - Every secret variable in both example files is empty.
  - The history holds one non-empty `POSTGRES_PASSWORD=` line: the old development default `aslms` in an earlier
    `.env.example`. The audit already flagged it. Preflight refuses it in production.
  - The Postman collection holds `{{placeholders}}` only.
  - `docs/napix_integration_notes.md` holds an HMAC test vector made with the hash key `15081947`, which the
    specification publishes.
  - The test keys (`test-key-16bytes`, `secret-test`) are fakes.
  - The PEM header in `test_ops_unit.py` is an assertion about a key the test generates. No key is stored.
  - This was a pattern search, not a full scanner. Decision 8 makes a full-history gitleaks scan a condition of the
    first push.
- **`docs/specs/samples` (decrypted live NAPIX responses, 1.4 MB):**
  - No token, key, client id, department id, e-mail address of a person or mobile number. The one e-mail address
    is the NIC contact inside the API's own overview text.
  - `overview_response.json` is an encrypted envelope: ciphertext under the live NAPIX auth key, plus its HMAC, of
    the public overview text. It does not reveal the key.
  - The samples do hold **personal data from public court records**:
    - names of petitioners, respondents and advocates (`pet_name`, `res_name`, `pet_adv`, `res_adv`, the
      party-name and advocate-name search results);
    - judges' names, case numbers and CNRs;
    - the FIR fields (null in these samples);
    - three full order PDFs (`order_*.pdf`) and a cause-list PDF.
  - The same kind of material is in `backend/tests/fixtures/causelists/*.pdf`. Real CNRs also appear in the
    decisions log and reports.
  - The test suite depends on these files: the coverage test, the scripted gateway and the cause-list parser tests.
  - Conclusion: the samples are fine in a **private** repository with named collaborators. They are not fine in a
    public one without redaction, which would be a separate item.
- **`docs/specs/pdf`:** the e-Committee API specifications and the NAPIX subscriber manual, 11.7 MB. They contain no
  credentials. Their licence for redistribution is unknown, which is another reason to keep the repository private.
- Size: the largest file is 5.4 MB and the packed history is small. Git LFS is not needed.

Not covered:
- a server-side scheduler that runs team cycles on GitHub (it would need an AI API key in GitHub; the owner's
  decision later);
- running the whole suite as `aslms_app` (row 84 widens that; `test_app_role.py` stays the dedicated module);
- dependency lock files (follow-up row, decision 15);
- moving the repository to a government Git server.

## Decisions

1. **The remote is a private GitHub repository: `nayanlhuzuri/aslms` by default** (owner check, Open questions 1
   and 2). Private because of the court material and the specification PDFs listed above.
   - The personal account is the default because it exists today. A later transfer to a SeMT/AMTRON organisation
     keeps the history, tags, Actions settings and redirects.
   - Forking is disabled. Collaborators are named people only.
   - *Alternatives:* a public repository (refused: personal data); a self-hosted Gitea or GitLab at the SDC (the
     workflows translate, and Gitea Actions reads the same YAML). This becomes the choice if State or AMTRON policy
     does not allow the source on github.com, which only the owner can confirm.

2. **The first push is an owner action, after two scans** (Verification, part 2). This item builds and documents
   everything locally and pushes nothing. The owner:
   - creates the empty repository (no README, licence or `.gitignore`);
   - runs `backend/tools/repo_policy.py history` and a full-history `gitleaks git` scan, both clean;
   - adds `origin`;
   - pushes `main` and the `feature/*-done` tags.

   Old local `feature/*`, `design/*` and `worktree-agent-*` branches are not pushed. Their work is already on
   `main` as squash commits.

3. **CI is GitHub Actions: one workflow, `.github/workflows/ci.yml`.**
   - **When it runs:** on `pull_request` (any branch into `main`), on `push` to `main`, and by hand
     (`workflow_dispatch`).
   - **Settings:**
     - `permissions: contents: read` at the top. The workflow token cannot write.
     - Concurrency group `ci-<ref>`. A newer run cancels an older one on pull-request refs, never on `main`.
     - Every job runs on `ubuntu-latest`, with a timeout.
   - **Jobs:**

   | Job | Steps | Timeout |
   |---|---|---|
   | `changes` | `git diff --name-only` between the base and the head (the whole tree on a first push, a manual run or a missing base). Sets `code=false` only when every changed path is on the docs-only list: `docs/design/`, `docs/reports/`, `docs/audits/`, `docs/team/`, `docs/backlog.md`, `docs/claude_ASLMS_design_decisions.md`, `README.md`, `CLAUDE.md`, `docs/*.docx`. Any other path, including `docs/operations.md`, `docs/schema/` and `docs/specs/` (tests read them), sets `code=true`. Plain shell; no third-party action. | 5 min |
   | `policy` | Always. `repo_policy.py tree`, then `repo_policy.py range <base>..<head>` (decision 9). gitleaks on the commits of the push or the pull request (decision 8). actionlint on `.github/workflows/`. | 10 min |
   | `backend` | If `code`. Python 3.12 (`actions/setup-python`, pip cache keyed on `backend/pyproject.toml`). `pip install -e "backend[dev,redis]"`. Then, in `backend/`: `ruff check .`, `ruff format --check .`, and `pytest -q -ra --junitxml=…` against the Postgres service (decision 4). The JUnit file is uploaded, kept 7 days. | 45 min |
   | `frontend` | If `code`. Node 22 (`actions/setup-node`, npm cache keyed on `frontend/package-lock.json`, plus `actions/cache` for `frontend/.next/cache`). `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`, `npm run gen:api`, then `git diff --exit-code -- frontend/src/lib/api/schema.d.ts`. | 20 min |
   | `compose` | If `code`. Throwaway settings (decision 6). `docker compose config -q`. `docker compose --profile '*' build` (every image, profiles included). `docker compose up -d --wait --no-deps web`. `python backend/tools/portal_smoke.py --base http://localhost:3000`. `promtool test rules` in the pinned `prom/prometheus:v3.7.2` image. On failure it uploads `docker compose logs web` (7 days). Always `docker compose down -v`. | 30 min |
   | `ci-ok` | Needs all of the above. Fails if any of them failed or was cancelled; a skipped job counts as passed. This is the one status a branch rule can require (decision 11). | 2 min |

   - **Versions:** Python 3.12 is the backend image's version (`python:3.12.15-slim`). Node 22 is the portal image's
     major version (`node:22.23.3-alpine`). A unit test keeps the workflow and the Dockerfiles in step
     (decision 14).
   - **Caching:**
     - pip and npm caches through the setup actions;
     - the Next.js build cache through `actions/cache`;
     - Docker layers through `docker/setup-buildx-action` and `docker buildx bake -f compose.yml` with
       `type=gha`.

     If bake does not load images under the names Compose expects (`COMPOSE_PROJECT_NAME=aslms`), the developer
     falls back to a plain `docker compose build` and records it as a deviation. The gate is "every image builds",
     not the cache.
   - **Pinning:** every action is pinned to a full commit SHA, with the version in a comment. Dependabot keeps them
     current (decision 12).
   - *Alternatives:* one workflow per gate (more YAML, the same minutes); path filters on the trigger (a required
     check would then wait forever on a skipped workflow; the `changes` job avoids that).

4. **A test database per run, the same locally and in CI** (`backend/tests/db/conftest.py`). This fixes audit
   Area 3.
   - **The URL.** `ASLMS_TEST_DATABASE_URL` keeps its meaning: the server, the credentials and a base name
     (default `aslms_test`).
   - **The name.** When `conftest.py` is imported, it computes the run's database name:
     `<base>_<UTC yyyymmddHHMMSS>_<6 random hex>`, for example `aslms_test_20261020101500_a1b2c3` (lowercase,
     under 63 characters).
   - **`TEST_URL`** becomes the base URL with that database (`make_url(...).set(database=...)`). It stays a module
     constant, so the 17 modules that import it are unchanged.
   - **The session fixture `db_url`:**
     - connects to the `postgres` maintenance database on the same server with AUTOCOMMIT;
     - drops stale run databases: a name that matches `^<base>_\d{14}_[0-9a-f]{6}$` exactly, with a timestamp
       older than 24 hours and no session in `pg_stat_activity`. A plain `DROP DATABASE` is used, never `FORCE`, so
       a live run is never touched. A name that does not match is never dropped. That includes the old
       `aslms_test` and the application's `aslms`;
     - runs `CREATE DATABASE "<name>" TEMPLATE template0 ENCODING 'UTF8'`;
     - pre-creates the three cluster roles if they are missing, under the cluster lock below. 0001's
       `IF NOT EXISTS` block is then a no-op, and two first runs cannot race on `CREATE ROLE`.
   - **`migrated`** upgrades the new, empty database to head. The wipe and the downgrade to base are not needed on
     a fresh database. The migration-cycle tests still do their own downgrades and upgrades.
   - **At the end of the session**, the database is dropped (`DROP DATABASE … WITH (FORCE)`, its own database
     only) after the engines are disposed. A killed run leaves its database behind, and the next run's sweep
     removes it after 24 hours.
   - **Variables:** three test-only environment variables (not application settings, never read from `.env`):

   | Variable | Default | Meaning |
   |---|---|---|
   | `ASLMS_TEST_DB_PER_RUN` | `1` | `0` uses the named database as before (wipe, downgrade, upgrade), for debugging with `psql`. In this mode the fixture refuses a database whose name does not contain `test`, so a mistyped URL can never wipe `aslms`. |
   | `ASLMS_TEST_KEEP_DB` | `0` | `1` keeps the run database at the end and prints its name. |
   | `ASLMS_TEST_REQUIRE_DB` | `0` | `1` turns "database not reachable" into a failure instead of a skip. CI sets it, so the database tests can never be silently skipped. |

   - **The URL's user needs `CREATEDB`.** The Compose superuser `aslms` and the CI service user have it. Without it
     the fixture fails with a message naming `ASLMS_TEST_DB_PER_RUN=0`.
   - *Alternatives:* `pytest-xdist`-style names per worker (no xdist here; the naming leaves room for it later);
     templates cloned from a migrated database (faster, but a stale template hides a migration change); a separate
     Postgres container per local run (heavier; a possible follow-up, Open questions 9).

5. **Cluster-wide state is serialised, not shared blindly.**
   - **The cluster lock.** `conftest.py` gains `cluster_lock()`: a session advisory lock,
     `pg_advisory_lock(hashtext('aslms-test-cluster'))`, taken on a connection to the **`postgres` maintenance
     database**. Advisory locks are scoped to a database, so the lock must live in a database every run shares.
   - **Who takes it:**
     - the `migrated` fixture, around its upgrade to head;
     - the role pre-creation in decision 4;
     - every test marked `migration_cycle`. A new marker, registered in `backend/pyproject.toml`. An autouse
       fixture takes the lock for marked tests.
   - **Which tests are marked:** every test that calls `command.upgrade` or `command.downgrade`. Each
     `test_migration_*.py` module gets `pytestmark = pytest.mark.migration_cycle`. The tests in `test_migrations.py`,
     `test_memberships.py`, `test_documents_upload.py`, `test_case_search.py`, `test_safety_fixes.py` and
     `test_sourcetrace.py` that cycle migrations are marked one by one.
   - A unit test enforces the rule (Tests).
   - **Why:** 0020's downgrade revokes `pg_monitor` for every database on the server. Without the lock, one run's
     migration test can break another run's assertion, or briefly the development exporter's statistics. That last
     effect exists today. The lock limits it to the seconds a migration cycle takes.
   - **Concurrency:** runs still overlap in everything else, which is all the data work.

6. **CI holds no secrets at all.**
   - **No GitHub repository or environment secrets are created.** In particular, never a NAPIX credential, a mail
     token, a JWT secret or a SourceTrace key (operations.md section 19 says so).
   - **The workflow sets these at the top level:**
     - `NAPIX_ENABLED: "false"`;
     - the NAPIX credential variables, empty (`NAPIX_CLIENT_ID`, `NAPIX_CLIENT_SECRET`, `NAPIX_DEPT_ID`,
       `NAPIX_AUTH_KEY`);
     - `MAIL_BACKEND: console`;
     - `SOURCETRACE_ENABLED: "false"`;
     - `APP_ENV: test`. Row 94 makes `dev` / `prod` / `test` the valid values. If row 94 is not merged first,
       `test` still behaves as non-prod today.
   - **NAPIX:** the scripted gateway (`httpx.MockTransport`) is the only NAPIX the tests know. A step in `backend`
     fails the job if any NAPIX credential variable is non-empty.
   - **The test database** uses a constant password, `aslms-ci`. It is a throwaway service container reachable only
     on the runner, not a secret.
   - **The `compose` job** generates its required Compose values into `$GITHUB_ENV` and masks each with
     `::add-mask::`. Each comes from `openssl rand -hex 32`: `POSTGRES_PASSWORD`, `ASLMS_APP_PASSWORD`,
     `ASLMS_READONLY_PASSWORD`, `REDIS_PASSWORD`, `ASLMS_JWT_SECRET`, `GRAFANA_ADMIN_PASSWORD`, and
     `FLOWER_BASIC_AUTH=ops:<hex>`. It also sets `PORTAL_BASE_URL=http://localhost:3000`, `COOKIE_SECURE=false`,
     `APP_ENV=dev` and `COMPOSE_FILE=compose.yml:compose.dev.yml`.
   - **No `.env` file is written.** Every service's `env_file` is `required: false`.
   - **Only `web` is started.** It holds no secret, and `portal_smoke.py` needs nothing else. `init`, `api` and the
     worker never start in CI, so nothing could reach NAPIX even by mistake.

7. **The Postgres service container.**
   - **Image:** `postgres:16.15`, the image `compose.yml` pins.
   - **Settings:** `POSTGRES_USER=aslms` and `POSTGRES_PASSWORD=aslms-ci`. Port 5432 is mapped on the runner. Health
     is `pg_isready`.
   - **Test URL:** `ASLMS_TEST_DATABASE_URL=postgresql+psycopg://aslms:aslms-ci@127.0.0.1:5432/aslms_test`, with
     `ASLMS_TEST_REQUIRE_DB=1`.
   - **Speed:** service containers cannot take server arguments. A step therefore runs
     `ALTER SYSTEM SET fsync = off`, `synchronous_commit = off` and `full_page_writes = off`, then
     `pg_reload_conf()` (all three reload without a restart). This is speed only, on a disposable cluster.
   - **No pilot settings:** none of the pilot's `-c` settings (memory, WAL, logging) matter to the tests. The
     developer confirms that the suite does not depend on `idle_in_transaction_session_timeout`. If a test does,
     the step sets it too.

8. **Secret scanning: gitleaks in CI, and the owner's scans before the first push.**
   - **The tool:** the gitleaks CLI (MIT licence), a pinned 8.x release run from its official image by digest. The
     `gitleaks-action` is not used: it needs a licence key for organisation accounts.
   - **Configuration:** `.gitleaks.toml` extends the default rules with ASLMS rules:
     - a non-empty `NAPIX_CLIENT_ID`, `NAPIX_CLIENT_SECRET`, `NAPIX_DEPT_ID` or `NAPIX_AUTH_KEY` value;
     - Mailtrap API tokens;
     - a `-----BEGIN … PRIVATE KEY-----` block.

     Its allowlist is commented entry by entry: the published hash key and its test vector, the test fakes,
     `frontend/package-lock.json` integrity hashes, and the specification PDFs.
   - **When it runs:**
     - in `policy`, on the commits of the push or pull request (`--log-opts=<base>..<head>`);
     - every week over the full history, in a second workflow, `.github/workflows/secret-scan.yml` (schedule
       Sunday 21:00 UTC = Monday 02:30 IST, plus `workflow_dispatch`).
   - **A true finding is never "fixed" by an agent.** History rewriting and key rotation are owner decisions.
   - **GitHub's own secret scanning and push protection** are switched on if the account's plan offers them for a
     private repository (Open questions 3). gitleaks covers the gap either way.

9. **What never reaches the remote is enforced three times:** by `.gitignore`, by
   `backend/tools/repo_policy.py`, and by gitleaks.
   - **`.gitignore` gains:** `*.dump`, `*.p12`, `*.pfx`, `*.postman_environment.json` and `roles-*.sql`.
   - **`repo_policy.py`** (standard library only; prints the path, the line and the rule, never the matched value)
     has three modes:
     - `tree`: the tracked files (`git ls-files`);
     - `range <a>..<b>`: every path and every added line in those commits;
     - `history`: every commit reachable from `main`.

     Its rules:
     1. **Forbidden paths:**
        - `.env` and `.env.*` in any folder, except `.env.example`;
        - `*.pem`, `*.key`, `*.p12`, `*.pfx`;
        - `backups/**`;
        - `data/**`, except `frontend/src/**/data/**`;
        - `infra/proxy/certs/**`, `infra/clamav/freshclam.conf`;
        - `docs/specs/napix/hc/samples/**` (unreviewed `napix-check` output);
        - `*.dump`, `roles-*.sql`;
        - `.claude/settings.local.json`, `.claude/worktrees/**`;
        - `*.postman_environment.json`;
        - `cause-list-directory/**`, `case_documents/**`, `order_documents/**`.
     2. **A non-empty value for a secret variable in an example env file:** `POSTGRES_PASSWORD`,
        `ASLMS_APP_PASSWORD`, `ASLMS_READONLY_PASSWORD`, `REDIS_PASSWORD`, `ASLMS_JWT_SECRET`,
        `ASLMS_SUPERADMIN_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`, `FLOWER_BASIC_AUTH`, the four NAPIX credentials,
        `MAILTRAP_API_TOKEN`, `SMTP_PASSWORD` and `SOURCETRACE_API_KEY`.
     3. **The NAPIX switch turned on in configuration.** `NAPIX_ENABLED` set to true in any of these:
        `.env.example`, `compose*.yml`, `.github/**`, `infra/**`, a `Dockerfile`, `backend/pyproject.toml` or
        `backend/alembic.ini`; or a `napix_enabled` field whose default is the boolean true under
        `backend/aslms/`. Documentation that shows the owner's shell prefix is not configuration and is not
        matched.
     4. **A private-key block** in any tracked text file.
     5. **A literal NAPIX credential** (`NAPIX_CLIENT_ID|CLIENT_SECRET|DEPT_ID|AUTH_KEY` followed by `=` or `:` and a
        value that is not empty, `""`, `${…}`, `<…>` or `{{…}}`) in any tracked text file.
     6. **A file over 20 MB.**
   - **An optional pre-push hook,** `.githooks/pre-push`, runs `repo_policy.py range` on the outgoing commits, and
     gitleaks when it is on `PATH`. The owner switches it on with `git config core.hooksPath .githooks`. Nothing is
     switched on silently.
   - **The `.claude/hooks/guard.py` additions** (enforced by the harness):
     - deny `git push` with `--force`, `-f`, `--force-with-lease`, `--mirror`, `--all`, `--delete` or `-d`, a refspec
       that starts with `+` or `:`, or any remote other than `origin`;
     - deny `git remote add`, `git remote set-url`, `git remote remove` and `git config remote.*`;
     - deny `gh secret`, `gh repo create`, `gh repo delete`, `gh repo edit`, `gh repo rename`, `gh repo archive` and
       `gh api`.

     The remote and the repository's settings are the owner's.

10. **The team keeps merging locally; the integrator then pushes `main` and the tag.**
    - **Deviation** from the team rule "never push" (decisions log, 4 Oct 2026). Owner check, Open questions 4.
    - **The new integrator steps, after the merge commit, the report and backlog commit, and the tag:**
      - when `git remote get-url origin` succeeds: `git push origin main`, then
        `git push origin refs/tags/feature/<slug>-done`;
      - fast-forward only. A refused push (main moved on the remote, network failure, no credentials) leaves
        `merged: yes, pushed: no` with the reason in the report. Never a retry with force, never a rebase. The
        owner pushes later.
    - **The gate before merging:** when `gh` is installed and signed in, `gh run list --branch main --limit 1` for
      `origin/main`'s head. A `failure` there stops the integrator before it merges ("CI is red on main: <url>").
      That way a broken `main` blocks further merges, not designs. Without `gh` the report says "CI status
      unknown" and the cycle goes on (Open questions 6).
    - **The report** records the pushed commit and, through `gh run list --commit <sha>`, the run's address.
    - **Commits on `main` outside a cycle** (`/team-approve`, design-note merges, the owner's own) go to the remote
      with the next push of `main`.
    - **Permissions:** `.claude/settings.json` allows exactly `git push origin main`,
      `git push origin refs/tags/feature/*`, `gh run list*` and `gh run view*`. Every other `git push` stays in
      `ask`. The force forms are added to `deny`, besides the guard. `gh` is signed in by the owner
      (`gh auth login`). Its token lives in the Windows credential store, never in the repository or `.env`.
    - **The team documents change to match:**
      - `integrator.md`: the push and the CI check replace "never push";
      - `team-cycle/SKILL.md`: "only the integrator pushes, as its definition says";
      - `team-cycle.js`: the MERGE schema gains `pushed` and `ciRun`;
      - `team-status/SKILL.md`: how far `main` is ahead of `origin/main`, and the last three CI runs on `main`;
      - `docs/team/README.md`;
      - `definition-of-done.md`: "when a remote exists, `main` and the tag are pushed; a red CI run on `main` stops
        the next merge".
    - *Alternative (Open questions 4):* pull requests. The integrator would:
      - push `feature/<slug>`;
      - open a pull request with the report as its body;
      - wait for `ci-ok`;
      - merge with `gh pr merge --squash`;
      - fast-forward local `main`.

      Better as a gate, but every design approval and backlog edit would also need a pull request (or an admin
      bypass), and each cycle waits for CI. The workflow above already supports it unchanged.

11. **Branch and tag rules on GitHub, if the plan allows them for a private repository** (Open questions 3).
    - **A ruleset on `main`:** block force pushes and deletion, and require linear history.
    - **Pull requests and status checks are not required** under decision 10. A squash commit made locally has no
      checks yet, so a required check would refuse every integrator push.
    - **A tag ruleset on `feature/*-done`:** block update and deletion.
    - **Repository settings:**
      - Actions limited to GitHub-made actions and `docker/*`;
      - the default workflow token read-only;
      - "Allow GitHub Actions to create and approve pull requests" off;
      - Dependabot alerts on;
      - forking off.
    - Without rulesets (GitHub Free, private), the guard hook is the only enforcement against force pushes. The
      owner is the only person with write access.
    - With the pull-request alternative, the `main` ruleset also requires a pull request and the `ci-ok` check,
      without "up to date" (concurrent cycles would otherwise re-run CI for nothing). The owner keeps the admin
      bypass for emergencies.

12. **Dependabot** (`.github/dependabot.yml`) updates the `github-actions` ecosystem monthly, so the SHA pins do not
    rot. pip, npm and the Docker images are not added: the images are pinned on purpose and change through the
    upgrade procedure (operations.md section 8). Adding them is the owner's choice later.

13. **The minutes budget** (Open questions 5).
    - A full run is about 25–35 billed minutes: backend about 15, frontend about 6, compose about 10, policy 1.
      The jobs run in parallel, about 15 minutes on the clock. A docs-only push (design notes, approvals, backlog,
      reports) costs about 2.
    - One push of `main` per cycle plus the docs commits is roughly 35–45 minutes per cycle. GitHub Free includes
      2,000 private-repository minutes a month and Pro 3,000 (figures at the time of writing; the owner checks the
      account's billing page). That is enough for about 45–60 cycles a month.
    - Artifacts are kept 7 days to stay within the free storage.

14. **The workflow is tested like code.** A unit test reads `.github/workflows/ci.yml` with `pyyaml` (already a dev
    dependency) and fails on drift or a missing safety setting. Tests lists the checks.

15. **Follow-up rows** the scribe adds to the backlog at build time:
    - **`github-first-push`** (owner): the steps of Verification part 2, the first green run's address in the
      decisions log, and the repository settings of decision 11.
    - **`dependency-locks`**: `backend/pyproject.toml` has `>=` ranges and no lock, so CI can resolve newer packages
      than the owner's `.venv` or the image. Add a constraints file used by CI and the Dockerfile, or `uv.lock`.
    - **`test-postgres-service`** (optional, Open questions 9): a `postgres-test` service in `compose.dev.yml`
      under a `test` profile (tmpfs, `127.0.0.1:5434`). Local runs would then not share roles with the development
      database at all.

## Data
No table, column, reference code or migration. `docs/schema/schema.md` is unchanged.

## Services
No application service changes. The changes are in tooling and tests:

- **`backend/tests/db/conftest.py`** (decisions 4 and 5):
  - `TEST_URL` is computed per run;
  - `db_url` connects to the server, sweeps stale databases, creates the run database and pre-creates the roles
    under the cluster lock;
  - `migrated` upgrades the new database; in per-run mode the wipe and downgrade are skipped;
  - a session finaliser drops the run database (unless `ASLMS_TEST_KEEP_DB=1`);
  - new: `cluster_lock()`, the autouse lock for `migration_cycle` tests, the `test` substring guard for
    `ASLMS_TEST_DB_PER_RUN=0`, and the require-database switch;
  - unchanged: `wipe`, `wipe_if_migrated`, `clean_db`, `world`, `session`, the scripted gateway.
- **`backend/pyproject.toml`:** registers the `migration_cycle` marker under `[tool.pytest.ini_options]`
  (`markers`).
- **Test modules:** the `migration_cycle` markers (decision 5). No test logic changes.
- **`backend/tools/repo_policy.py`** (new, decision 9). A command-line tool: `tree | range <a>..<b> | history`. Exit
  status 0 when clean, 1 with findings. Pure functions, so the rules can be tested without git:
  - `check_path(path) -> list[str]`;
  - `check_text(path, text) -> list[tuple[int, str]]`.
- **`.claude/hooks/guard.py`:** the push, remote and `gh` denials (decision 9).
- **`.claude/settings.json`:** the narrow push and `gh run` permissions and the force-push denials (decision 10).
- **Team definitions** (decision 10): `integrator.md`, `team-cycle/SKILL.md`, `team-cycle.js`,
  `team-status/SKILL.md`, `docs/team/README.md`, `docs/team/definition-of-done.md`.
- **New files:**
  - `.github/workflows/ci.yml` and `.github/workflows/secret-scan.yml`;
  - `.github/dependabot.yml`;
  - `.gitleaks.toml`;
  - `.githooks/pre-push`.
- **`.gitignore`:** the additions of decision 9.
- **`docs/operations.md`:**
  - section 16 (Development) replaces the shared-database sentence with: the run database, the three variables,
    and the note that the old `aslms_test` database may be dropped once by hand;
  - a new **section 19, "Repository and CI"**:
    - the remote and who owns it;
    - the first-push procedure;
    - what never reaches the remote and why, including the samples finding above;
    - no NAPIX or other secrets in GitHub, ever;
    - what each CI job checks and how to read a red run;
    - the weekly secret scan and what to do on a finding (stop; the owner rotates the key and decides on history);
    - the pre-push hook;
    - the rulesets;
    - the minutes budget.
- **`README.md`:** the development quick start line on tests names the per-run database; a line that CI runs on
  GitHub.
- **Decisions log:** an entry when built, including the deviation in decision 10.

## API
None. No endpoint, `Permission` or audit action is added or changed.

## Jobs
No Celery or queue job. Two GitHub Actions workflows:
- **`ci.yml`:** on `pull_request` into `main`, `push` to `main` and `workflow_dispatch`. The jobs `changes`,
  `policy`, `backend`, `frontend`, `compose` and `ci-ok` of decision 3.
- **`secret-scan.yml`:** a weekly schedule (`cron: "0 21 * * 0"`, Monday 02:30 IST) and `workflow_dispatch`.
  gitleaks over the full history and `repo_policy.py history`. A failure e-mails the repository owner through
  GitHub's standard notification.

## Tests
Unit (`backend/tests/unit/`):
- `test_ci_workflow.py`:
  - `ci.yml` parses;
  - top-level `permissions` is `contents: read`;
  - `NAPIX_ENABLED` is `"false"` and the four NAPIX credential variables are empty in the workflow `env`;
  - no `${{ secrets.* }}` reference anywhere in `.github/workflows/`;
  - every `uses:` outside `./` is pinned to a 40-hex SHA;
  - the Python version equals the backend Dockerfile's major.minor (3.12);
  - the Node major version equals the frontend Dockerfile's (22);
  - the Postgres service image equals `compose.yml`'s `postgres` image;
  - `ASLMS_TEST_REQUIRE_DB` is `"1"` in `backend`;
  - the `changes` docs-only list contains no path a test reads: `docs/operations.md`, `docs/schema/` and
    `docs/specs/` are absent;
  - `ci-ok` needs every other job.
- `test_repo_policy.py`:
  - each rule fires on a synthetic path or text: a `.env`, `.env.prod`, `backups/x.dump`, `data/store/a.pdf`,
    `infra/proxy/certs/privkey.pem`, the switch set to true in a compose file, a `napix_enabled` field defaulting
    to true, a non-empty `NAPIX_AUTH_KEY=` in `.env.example`, a PEM private-key block, a 21 MB file. The test
    builds the switch-on strings at run time (by concatenation), because the guard hook refuses any file that
    contains them literally; the same applies to `repo_policy.py`'s own patterns and to `.gitleaks.toml`;
  - nothing fires on the allowed forms: `.env.example`, `frontend/src/app/data/page.tsx`, an empty assignment, a
    `${{ }}` or `<…>` placeholder, the shell-prefix example in a design note;
  - a finding's message never contains the matched value;
  - `tree` mode on the real checkout is clean (skipped when `git` is unavailable or the folder is not a
    checkout).
- `test_db_test_isolation.py`:
  - the run-database name matches the pattern and stays under 63 characters;
  - `TEST_URL` keeps the server and credentials of `ASLMS_TEST_DATABASE_URL` and changes only the database;
  - the sweep pattern matches no name outside `<base>_<14 digits>_<6 hex>` (it is checked against `aslms`,
    `aslms_test`, `aslms_test_x`, `aslms_restore_check`);
  - an AST scan of `backend/tests/db/*.py`: every test function that calls `command.upgrade` or
    `command.downgrade` is in a module or function marked `migration_cycle`;
  - with `ASLMS_TEST_DB_PER_RUN=0`, a URL whose database lacks `test` is refused.
- `test_guard_push.py`: `guard.py` run with tool-call JSON on stdin denies the forms of decision 9 and allows
  `git push origin main` and `git push origin refs/tags/feature/x-done`.

Database (`backend/tests/db/`):
- `test_run_database.py`:
  - the session's database name is the per-run name, not the base name;
  - the database exists while the session runs;
  - a database created by the test with a stale-looking name (timestamp 2 days old, no sessions) is dropped by the
    sweep function;
  - one with a fresh timestamp, and one with a non-matching name, are kept (the test drops its own leftovers);
  - the three roles exist after `db_url`.

The whole existing suite stays green unchanged apart from the markers. That is the main proof that the fixture
change is transparent.

## Verification
**Part 1, by the integrator before the merge (no remote yet):**
1. `cd backend && ruff check . && ruff format --check . && pytest -q`: green, with the counts recorded. If
   `ruff format --check` fails on files untouched by this item, the developer applies `ruff format` in its own
   commit first.
2. **Two sessions at once.** Start `pytest tests/db -q` twice in parallel against the development cluster. Both are
   green. Afterwards `select datname from pg_database where datname like 'aslms_test_%'` returns nothing (both
   dropped).
3. `ASLMS_TEST_KEEP_DB=1 pytest tests/db/test_run_database.py -q` leaves one database and prints its name. Drop it
   by hand afterwards.
4. **The CI backend job, reproduced in Linux containers with no secrets:**

   ```
   docker network create aslms-ci-check
   docker run -d --name pg-ci --network aslms-ci-check -e POSTGRES_USER=aslms -e POSTGRES_PASSWORD=aslms-ci postgres:16.15
   docker run --rm --network aslms-ci-check -v "<repo>:/src" -w /src/backend \
     -e ASLMS_TEST_DATABASE_URL=postgresql+psycopg://aslms:aslms-ci@pg-ci:5432/aslms_test -e ASLMS_TEST_REQUIRE_DB=1 \
     -e NAPIX_ENABLED=false python:3.12.15-slim sh -c 'pip install -q -e ".[dev,redis]" && ruff check . && pytest -q'
   ```

   Green, then remove `pg-ci` and the network. The frontend steps run the same way in `node:22.23.3-alpine`
   (`npm ci && npm run lint && npm run typecheck && npm test && npm run build`).
5. **The workflows:** actionlint on `.github/workflows/` (pinned `rhysd/actionlint` image) is clean.
6. **The policy scans:** `python backend/tools/repo_policy.py tree` and `history` are clean. A full-history
   `gitleaks git --redact` (pinned image) is clean with `.gitleaks.toml`. Each allowlist entry is justified in a
   comment.
7. The guard denies `git push --force origin main` and `git remote add x y` when tried through the tool. The
   `test_guard_push.py` results are enough evidence.
8. `docker compose build`, the `web` smoke and `promtool test rules`: unchanged gates, still passing.

**Part 2, by the owner (row `github-first-push`), after approval and the merge:**
1. Create the private repository `nayanlhuzuri/aslms`, empty. Apply the settings and rulesets of decision 11 that the
   plan offers.
2. On the owner's machine, with a clean `main`: run `repo_policy.py history` and the full gitleaks scan again.
3. Run `git remote add origin <url>`, `git push -u origin main` and `git push origin "refs/tags/feature/*"`.
4. Watch the first `ci.yml` run. It must be green on all jobs. Record its address and duration in the decisions log.
   A red job becomes a fix row; the integrator's next merge would stop on it anyway.
5. Run `gh auth login`. `/team-status` then shows CI. The next cycle's integrator push and its run complete the
   check.

## Open questions
These are owner checks. Each has a recommended default, and none blocks the design: everything in Part 1 is built the
same whatever the answers, and the answers are applied at the first push.

1. **Where the repository lives.** Default: a private repository under the personal account `nayanlhuzuri`, named
   `aslms`, transferred later to a SeMT or AMTRON organisation when one exists. An organisation now is equally
   possible; the workflows do not change.
2. **Whether State or AMTRON policy allows the source on github.com.** Default: yes, as the backlog row assumes. If
   not, a Gitea or GitLab server at the SDC with the same workflows (Gitea Actions); the CI design is unchanged.
3. **The GitHub plan.** Default: GitHub Free to start. At the time of writing, rulesets on a private repository and
   GitHub's own secret scanning need a paid plan: Pro (about USD 4 a month) gives rulesets and 3,000 minutes, and
   secret scanning on private repositories needs GitHub's paid Secret Protection. On Free the guard hook and gitleaks
   carry the load. Recommended if budget allows: Pro, for the `main` and tag rulesets.
4. **Who pushes, and how merges happen.** Default: the integrator merges locally as today, then pushes `main` and
   the tag under the narrow permission (decision 10). Alternatives: (a) only the owner pushes, by hand (agents never
   push; CI still checks every push of `main`); (b) pull requests with a required `ci-ok` check (decision 10's
   alternative).
5. **The Actions minutes budget.** Default: Free's 2,000 private minutes. Expect about 35–45 per cycle (decision 13).
   If cycles run many times a day, Pro's 3,000 minutes, or dropping the `compose` job from pushes that touch only
   `backend/` (not recommended: it is the gate that caught the 11 Oct render crash).
6. **A red or unknown CI on `main`.** Default: red stops the next merge; unknown (no `gh`) is reported and the cycle
   continues. Stricter: unknown also stops, which makes `gh` mandatory on the machine running cycles.
7. **The personal data in the samples and fixtures.** Default: keep them as they are in a private repository; they
   are public court records the tests depend on. Making the repository public later needs a separate redaction
   item first.
8. **The pre-push hook.** Default: offered, not switched on. The owner runs `git config core.hooksPath .githooks`
   once if wanted.
9. **A separate test Postgres for local runs** (follow-up row `test-postgres-service`). Default: not now. The
   per-run database and the cluster lock are enough. Worth doing if the development exporter's brief loss of
   `pg_monitor` during migration tests matters.
10. **Commit e-mail.** The history already carries the owner's commit address, visible to collaborators of a
    private repository. Default: leave it. GitHub's no-reply address can be used for future commits if preferred.

## Deviations
Recorded by the developer at build time (20 Oct 2026).

1. **`.claude/settings.json` is not changed by the build.** Decision 10's permission entries widen what the agents
   may run, so they are left for the owner to apply by hand: in `allow`, `Bash(git push origin main)`,
   `Bash(git push origin refs/tags/feature/*)`, `Bash(gh run list*)` and `Bash(gh run view*)`; in `deny`,
   `Bash(git push --force*)`, `Bash(git push -f*)`, `Bash(git push --force-with-lease*)` and
   `Bash(git push --mirror*)`. Until then every `git push` stays in `ask`, and the guard hook already refuses the
   force forms. The integrator's definition handles a declined push as `pushed: no`.
2. **Images are built with `docker/bake-action` and tagged per target.** `docker buildx bake -f compose.yml` gives
   every service a target but no tag (no service in `compose.yml` names an `image:`), so the `compose` job reads the
   target list from `bake --print` and sets `<target>.tags=aslms-<target>` (the names Compose gives with the project
   `aslms`), plus one shared `type=gha` cache for all targets. A step checks that every image is loaded under that
   name before `docker compose up --no-deps web`. The bake action runs with `source: .` (the checkout, not the Git
   context). This is unproven until the first run on GitHub; if it fails there, the fallback in decision 3 (plain
   `docker compose --profile '*' build`) applies.
3. **The history holds two more old development defaults than the design listed.** Besides `POSTGRES_PASSWORD=aslms`
   (commit 6f238048), commit ec1254cb set `ASLMS_APP_PASSWORD=aslms_app` and `ASLMS_READONLY_PASSWORD=aslms_readonly`
   in `.env.example`. All three are on preflight's weak-value list. `repo_policy.py` keeps a commented
   `HISTORY_ALLOWLIST` of exactly these three (commit, path, rule) entries, used only by `range` and `history`; the
   `tree` mode has no exceptions. gitleaks does not flag them.
4. **Rule details in `repo_policy.py`** (the design is silent on them):
   - the switch rule also matches `1`, `yes` and `on`, the other values the settings read as true;
   - a private-key finding is a line that is only the BEGIN marker, or the marker followed by an escaped `\n` and
     key material on one line; an assertion that mentions the marker (`test_ops_unit.py`) is not a block;
   - for the credential and example-env rules, a value that starts with `#` (a comment) or a backtick (the end of a
     Markdown code span such as `` `NAPIX_AUTH_KEY=` ``), or that is only closing punctuation (`"NAME=",` in Python),
     is empty;
   - `range` accepts any git revision list after `--` (the pre-push hook passes `<sha> --not --remotes=<remote>` for
     a new ref); `history` takes `--branch` (CI passes `HEAD`, the checked-out `main`).
5. **gitleaks allowlist.** Five commented entries: the NAPIX `response_token` in `docs/specs/samples/*.json` and the
   known-answer vectors in `crypto.py` / the integration notes (HMACs under the published hash key), the test fakes
   (the generic rule only, under `backend/tests/`; the three ASLMS rules still apply there), the npm integrity hashes,
   and the specification PDFs. The full-history scan with gitleaks 8.30.1 is clean (275 commits).
6. **Guard extensions.** Besides the forms in decision 9, the guard refuses `git push` with no remote named (its
   remote cannot be checked), `--prune` and `--repo`, `git remote rm` and `rename`, and `gh repo unarchive` and
   `set-default`. Commands inside `bash -c` / `pwsh -Command` are checked too.
7. **The per-run helpers live in `backend/tests/db/rundb.py`** (pure functions, the sweep, the cluster lock), imported
   by `conftest.py`, so the unit tests use them without a database. `cluster_lock()` is re-entrant within a thread,
   so the role pre-creation, `migrated` and a marked test never wait on themselves.
8. **Pinned tools:** gitleaks 8.30.1 and actionlint 1.7.12 run from their images by digest (`GITLEAKS_IMAGE`,
   `ACTIONLINT_IMAGE` in the workflow `env`); the actions are checkout v7.0.1, setup-python v7.0.0, setup-node
   v7.1.0, cache v6.1.0, upload-artifact v7.0.2, setup-buildx-action v4.4.1 and bake-action v7.5.0, each by commit SHA.
9. **CI installs the backend with `backend/constraints-ci.txt`.** Reproducing the `backend` job in Linux
   containers (Verification part 1, step 4) showed that an unconstrained `pip install` resolves newer packages than
   the owner's `.venv` (FastAPI 0.150 and Starlette 1.9 against 0.142 and 1.7): Starlette's new reason phrases
   ("Content Too Large") make `test_committed_openapi_matches_the_app` fail, and a newer ruff could reformat files.
   So CI would be red from its first run. The smallest fix: a constraints file holding the `.venv`'s versions
   (`pip freeze --exclude-editable`), used only by CI (`pip install -c`). The `dependency-locks` row still replaces
   it with one lock used by CI and the Dockerfile alike; until then the file is refreshed by hand when the `.venv`
   is upgraded.
10. **Two tests made independent of the CI environment** (the only test-logic changes besides the markers):
    `test_case_search.py::test_migration_backfill_fills_the_vector` built its Alembic URL by replacing the masked
    password with the literal `aslms`, which fails against any other password (CI's `aslms-ci`); it now renders the
    engine's URL with the password. `test_mailer.py` removes `MAIL_BACKEND` and the mail variables from the process
    environment for its tests, because CI sets `MAIL_BACKEND=console` for the whole run (decision 6) and the tests
    check the automatic choice.
11. **The OpenAPI export is the same on Python 3.12 and 3.13.** The image and CI run 3.12 (decision 3), the owner's
    `.venv` runs 3.13, and 3.13 renamed some `http.HTTPStatus` phrases that FastAPI uses as default response
    descriptions (413 "Request Entity Too Large" became "Content Too Large"). The committed `frontend/openapi.json`
    carries the 3.13 names, so `test_committed_openapi_matches_the_app` failed on 3.12. `backend/tools/export_openapi.py`
    now maps the four old phrases (413, 414, 416, 422) to RFC 9110's when a response carries exactly the old one;
    on 3.13 nothing changes and `openapi.json` is unchanged.
12. **Observed once, not reproduced:** the first Linux reproduction also failed
    `test_discovery_run.py::test_a_search_stores_records_and_queues_dossiers` and
    `::test_a_malformed_cino_is_counted_not_stored` (`result` still empty after the run). Both passed alone and in
    the second full Linux run. If CI shows them again, they become a fix row (a likely ordering or timing dependency
    in the discovery runner's tests), not a change here.
13. **Left to the scribe:** the decisions-log entry, `CLAUDE.md` "Current focus" and the follow-up rows of decision 15
   (`github-first-push`, `dependency-locks`, `test-postgres-service`).
14. **The guard reads every line of a command (review fix).** `segments()` treated a line break as plain
    whitespace, so a multi-line command was checked as one simple command and a push, remote or `gh` command after
    the first line passed. An unquoted line break (`\n` or `\r\n`) now separates commands like `;`. A backslash
    before the break continues the line; so does PowerShell's backtick, and because a POSIX shell does not join on
    a backtick, such a command is checked both ways. A break inside quotes stays part of its word, so a multi-line
    commit message is still one argument. Comments, heredoc bodies (`<<EOF`, `<<-EOF`, quoted delimiters) and
    PowerShell here-strings (`@'…'@`, `@"…"@`) are dropped before the split, so an apostrophe or a command-like line
    inside them neither shifts the quoting nor counts as a command. `test_guard_push.py` covers the multi-line
    forms. Known limit, as before: a `"` inside a heredoc nested in a double-quoted `$(…)` can still shift the
    quoting; the guard is a backstop to the permission rules, not a shell parser. The unused `low` variable was
    removed so `guard.py` is `ruff` clean.
