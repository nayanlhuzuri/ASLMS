# Design: Dependency locks — one Python lock used by CI and the images alike

```
slug: dependency-locks
status: approved
author: architect
date: 2026-11-03
approved_by: owner on 2026-11-03
```

## Context
Backlog row 98, a follow-up of row 15 (`docs/design/github-and-ci.md`, decision 15 and deviation 9). The owner moved it
up on 3 Nov 2026 to be the next build after row 201, after the scheduler outage of that day (decisions log, "Hotfix:
scheduler down after kombu 5.7.0 (2026-11-03)").

**What happened.** `backend/Dockerfile` runs `pip install ".[redis]"` against `backend/pyproject.toml`, whose
requirements are open `>=` ranges, so every image build resolves whatever PyPI holds that minute. The 14:20 IST build
of 3 Nov installed kombu 5.7.0, released shortly before; its Redis transport imports `packaging` without declaring it,
and the scheduler failed at start from about 14:45 to 15:37 IST. CI did not see it, because CI installs with
`-c backend/constraints-ci.txt`, a hand-refreshed `pip freeze` of the owner's Windows `.venv` (kombu 5.6.2). The hotfix
on `main` holds `kombu>=5.4,<5.7` and declares `packaging>=24`.

**The drift is wider than kombu.** Measured on 3 Nov 2026 (read-only: `pip freeze` in a throwaway container of the
current `aslms-api:latest`, built 15:36 IST, and the `.venv`'s installed distributions):

| | CI and the `.venv` (constraints-ci.txt) | The running images |
|---|---|---|
| fastapi / starlette | 0.142.2 / 1.7.0 | 0.162.0 / 1.10.0 |
| pydantic / pydantic-core / pydantic-settings | 2.13.5 / 2.46.5 / 2.15.0 | 2.14.2 / 2.50.2 / 2.16.2 |
| sqlalchemy / alembic / psycopg | 2.1.1 / 1.20.0 / 3.3.6 | 2.1.6 / 1.20.1 / 3.3.7 |
| python-dateutil | 2.9.0.post0 | **4.0.0** |
| uvloop (Linux only) | not in the file (a Windows freeze); CI resolves it freely | 0.23.0 |

27 packages in all run in production at versions CI has never tested. Row 15's own reproduction showed that a newer
Starlette changes HTTP reason phrases and turns a test red, so these are not cosmetic differences.

**What is in place.**
- Backend: Python 3.12.15 in the image (`python:3.12.15-slim`, Linux x86_64, pip 25.0.1); Python 3.12 in CI
  (`actions/setup-python`, `python-version: "3.12"`); Python 3.13.0 in the owner's Windows `backend/.venv` (pip 24.2).
  Seven Compose services are built from `./backend`: `init`, `api`, `worker`, `scheduler`, `backup`, `migrate`
  (profile `ops`) and `ops-exporter` (profile `monitoring`). `migrate` refuses an image built from other code
  (`services/source_check.py`: digests of `/app/aslms` and `/app/migrations` against `/src`, which is `./backend`
  mounted read-only); the installed dependencies are not part of that comparison today.
- Frontend: already locked. `frontend/Dockerfile` (`node:22.23.3-alpine`) and the CI `frontend` job both run
  `npm ci` on `frontend/package-lock.json` (lockfile v3, 569 entries each with an `integrity` hash, and every
  platform's optional packages: `@next/swc-*` for linux-x64 gnu and musl and win32, the `@rollup/*` and `@esbuild/*`
  platform packages). `npm ci` fails when `package.json` and the lock disagree. The browser check image
  (`frontend/e2e/Dockerfile`) runs `npm ci` on `frontend/e2e/package-lock.json` and stops when its Playwright
  differs from the image's. The one gap is that CI asks for Node `"22"` while the image pins `22.23.3`.

**What this does not cover.** No upgrade of any library: the first lock holds the versions CI tests today (decision 4);
bringing them to current releases is a later, separate refresh. No change to application behaviour, schema, API or
portal. No automatic dependency updates (Dependabot stays on the action pins only, github-and-ci decision 12). The
monitoring images, PgBouncer and the base images are already pinned by tag or digest and are not touched. The browser
check in CI stays row 125.

## Decisions

1. **The lock is `backend/uv.lock`, made by uv, with two generated requirement files for pip.**
   - `backend/uv.lock` is the one lock. `uv lock` resolves once for every platform and Python version the project
     allows (a universal lock, with environment markers), and records every distribution file's sha256.
   - It is exported, never edited by hand, to two hashed requirement files:
     - `backend/requirements/image.txt`: the runtime dependencies, the `redis` extra and the `build` group
       (decision 3);
     - `backend/requirements/dev.txt`: the same plus the `dev` extra.
   - Every line in both is `name==version` with environment markers where they apply and every `--hash=sha256:` the
     lock knows for that version (each wheel and the sdist). Neither names the project itself (`--no-emit-project`).
   - The exports are views of the one lock, and CI proves them byte-for-byte current (decision 7). `image.txt` is a
     subset of `dev.txt` with the same versions (tested), so CI always tests exactly the versions the images run.
   - Alternatives:
     - **pip-tools** (`pip-compile --generate-hashes`): resolves for the interpreter and platform it runs on. Linux
       (image, CI) and Windows (`.venv`) would need two locks, or compiling inside a container. It has no built-in
       "is the lock current" check; that means re-resolving and diffing, which depends on the network and on preferences.
     - **`uv pip compile --universal`** without `uv.lock`: one universal file, but again no `--locked` check.
     - **`uv sync` in the Dockerfile and CI**: needs the uv binary in the image build and its own virtual environment
       and editable defaults. Plain pip from the export verifies the same hashes and leaves the image as it is.
   - Reason: one universal lock across Linux 3.12 and Windows 3.13, a built-in staleness check (`uv lock --locked`),
     and plain `pip` at install time, so uv is a developer and CI tool only. It is never in a running image.

2. **uv itself is pinned through the lock.** `uv` joins the `dev` extra (`uv>=<the version used at build time>`), so
   `dev.txt` pins it exactly and hash-checks it. The `.venv` and CI therefore run the same uv, invoked as
   `python -m uv`.
   - Alternatives:
     - the `astral-sh/setup-uv` action: refused, because the repository allows only GitHub-made and `docker/*`
       actions (operations.md section 19);
     - a uv image by digest: a second pin to keep current;
     - a separate tools file: a second lock.

3. **Coverage of the main dependencies and the `redis` and `dev` extras, plus a `build` group.**
   - Main `dependencies` and both extras are in `uv.lock`.
   - The `redis` extra (`redis>=5`) repeats a main dependency. It stays, so `.[redis]` and `.[dev,redis]` keep
     working wherever they are written, and both exports name it.
   - A PEP 735 dependency group `build = ["setuptools>=68"]` is added to `pyproject.toml`, so the build backend is
     locked and hash-checked too. Both installs of the project then use `--no-build-isolation`, and nothing outside
     the lock is fetched.
     - `python:3.12-slim` carries no setuptools.
     - Today build isolation downloads an unpinned setuptools at every build.
     - `[build-system] requires` is unchanged, for anyone who builds with isolation.
   - The developer confirms that the locked setuptools (70.1 or later, which has `bdist_wheel` built in) builds the
     wheel and the editable install alone.

4. **The first lock holds the versions CI tests today, so the running images move to them.**
   - The first `uv lock` is made with the versions of `constraints-ci.txt` as one-off constraints
     (`[tool.uv] constraint-dependencies`, removed again after the first lock). uv keeps locked versions on later
     runs, so a second plain `uv lock` changes nothing (the developer shows this).
   - Packages the Windows freeze could not name take these versions:
     - `uvloop` 0.23.0 (Linux only), the image's current version;
     - `setuptools` and `uv` (decisions 2 and 3), current at build time.
   - **For the owner's attention:** at the first deploy after this item, the images change 27 packages back to the
     tested set (fastapi 0.162.0 to 0.142.2, starlette 1.10.0 to 1.7.0, python-dateutil 4.0.0 to 2.9.0.post0 and the
     others in the Context table). This is intended: production then runs what the whole test suite passed on.
   - Alternative refused: lock the images' current versions. CI has never run them, and row 15 showed a newer
     Starlette turns a test red, so this item would grow into an upgrade.
   - Suggested follow-up row for the scribe: `dependency-refresh`, bringing the lock to current releases with one
     `deps.py lock --upgrade` and a green CI run.

5. **CI and the Dockerfile install only from the lock, hash-checked, wheels only.**
   - **Dockerfile.** `requirements/image.txt` is copied and installed *before* the code is copied, so the dependency
     layer is rebuilt only when the lock changes:
     ```
     COPY requirements/image.txt ./requirements/image.txt
     RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements/image.txt
     COPY pyproject.toml alembic.ini ./
     COPY aslms ./aslms
     COPY migrations ./migrations
     RUN pip install --no-cache-dir --no-deps --no-build-isolation . && pip check && <import smoke, decision 6> && <user setup as today>
     ```
   - **CI `backend` job:**
     - `python -m pip install --require-hashes --only-binary :all: -r backend/requirements/dev.txt`;
     - `python -m pip install --no-deps --no-build-isolation -e backend`;
     - `python -m pip check`;
     - the lock check (decision 7).
     The pip cache is keyed on `backend/requirements/dev.txt`.
   - Why each flag:
     - `--require-hashes` makes pip refuse any package or file the lock does not name.
     - `--only-binary :all:` refuses a silent source build; a missing wheel shows up at refresh time instead
       (decision 9).
     - `--no-deps` on the project install keeps the project from adding anything; pip has already checked the
       lock's own completeness in hash mode.

6. **An import smoke test in the image build catches an undeclared import.** CI's `dev.txt` is a superset (pytest
   brings `packaging`), so a runtime package that imports something it does not declare can pass CI and still break
   an image, which is the kombu case exactly.
   - After `pip check`, the Dockerfile imports what the services start from:
     - `aslms.cli.main` (init, worker, backup, migrate, ops-exporter);
     - `aslms.api.main` (api);
     - `aslms.jobs.celery_app` (scheduler);
     - `kombu.transport.redis` (the failed transport);
     - `uvicorn.loops.uvloop` (the Linux-only server loop).
   - A failure stops `docker compose build`, so the deploy keeps its old images. The CI `compose` job builds every
     image and fails the same way.
   - The smoke runs with `APP_ENV=test` and no secrets. If a module refuses to import without some setting, the
     developer passes a non-secret placeholder in that `RUN` line only, never as an image `ENV`, and records it.
   - Alternative refused: run the smoke only in CI. It would not stop a local deploy build.

7. **The guard: CI fails when `pyproject.toml` changes without the lock being refreshed.**
   - In the `backend` job, after the install, the step "Lock up to date" runs `python backend/tools/deps.py check`:
     - `python -m uv lock --locked` fails when `uv.lock` no longer matches `pyproject.toml`;
     - both exports are produced again from the lock (`uv export --frozen …`, to memory) and compared with the
       committed files.
   - A difference fails with the file's name and the command that fixes it.
   - An offline unit test does the first half without the network, so a local `pytest -q` catches a stale lock
     before CI does: it compares the requirements `uv.lock` records for the project (dependencies, extras, the
     `build` group) with `pyproject.toml`.
   - Alternatives refused:
     - a pre-commit hook: the team's commits go through agents and squash merges, and CI is the gate;
     - diffing a fresh `pip-compile`: depends on the network and on preferences.

8. **One command, `backend/tools/deps.py`, for the lock and the `.venv`.**
   - A stdlib-only script beside `export_openapi.py`. It is not in the image (the Dockerfile copies no `tools/`). It
     runs uv as `sys.executable -m uv`.
   - `deps.py lock [--upgrade | --upgrade-package NAME …]`: `uv lock` with the flags, then both exports. This is
     **the one documented command to refresh the lock**:
     - adding or changing a requirement in `pyproject.toml`: `deps.py lock` (existing pins are kept);
     - upgrading one package: `--upgrade-package NAME`;
     - upgrading everything: `--upgrade`.
   - `deps.py check`: decision 7.
   - `deps.py sync [--check]`: makes the running environment match `dev.txt` for its platform:
     - `pip install --require-hashes --only-binary :all: -r requirements/dev.txt`;
     - the editable project (`--no-deps --no-build-isolation -e .`);
     - `pip uninstall -y` of every installed distribution the lock does not name for this platform (never `pip` or
       `aslms`);
     - `pip check`.
     It reports any leftover it cannot remove, for example the broken `~slms` dist-info folder now in the `.venv`.
     `--check` only lists the differences and exits 1 when there are any.
   - The `.venv` needs no uv for `sync`: plain pip reads the export, so the first sync also brings uv in.

9. **Platforms and Python versions.**
   - `requires-python = ">=3.11"` is unchanged, and the lock is universal over it.
   - `[tool.uv] environments` limits resolution to `sys_platform == 'linux'` and `sys_platform == 'win32'`, the two
     platforms ASLMS runs on (no macOS forks).
   - `[tool.uv] required-environments` requires a wheel for Linux x86_64 and Windows AMD64. A refresh that picks a
     version without a wheel for either therefore fails at `deps.py lock`, not at a build. If the pinned uv
     interprets this over Python versions the project does not use, the developer narrows the markers and records it.
   - Platform-specific packages come out of the lock with markers:
     - `uvloop` (uvicorn's `standard` extra, not on Windows);
     - `colorama` (click on Windows).
     pip evaluates the markers at install time and picks the platform's wheel by hash.
   - The `.venv` stays on Python 3.13. The image and CI stay on 3.12.15, and the OpenAPI phrase mapping of row 15
     (decision 11) already covers the difference.
   - CI's `python-version` becomes exactly `"3.12.15"`, the image's version. If `actions/setup-python` cannot supply
     that exact version, it stays `"3.12"`, the test keeps checking major.minor, and the developer records it.

10. **`backend/constraints-ci.txt` is retired.** It is deleted in this item, with its mentions in `ci.yml`, operations.md
    section 19 and `test_ci_workflow.py`. A test asserts that it is gone. github-and-ci deviation 9 is superseded; the
    scribe records this in the decisions log, and the row 15 note stays as written (history).

11. **The hotfix pins: `packaging` stays, the `kombu` cap goes.**
    - `packaging>=24` stays a declared runtime dependency, with its comment: kombu's Redis transport imports it
      undeclared, and without the declaration the image set would lose `packaging` while CI's `dev.txt` (through
      pytest) kept it, hiding the fault. A test asserts it is in `image.txt`.
    - `kombu>=5.4,<5.7` becomes `kombu>=5.4`: the cap's own comment reads "until the lock file of row 98". The lock
      holds 5.6.2, so lifting the cap changes no installed version. A later move to 5.7 is a deliberate refresh,
      tested by CI and by the import smoke.
    - `pymupdf<2` stays, for its own reason (design document-ocr).

12. **The `migrate` source check also compares the dependency lock.**
    - The image keeps `/app/requirements/image.txt`, the file it installed from. `image_matches_source()` adds a third
      comparison: the sha256 of `/app/requirements/image.txt` against `/src/requirements/image.txt`.
    - A difference adds "dependency lock differs" to the exit-5 message (with the same rebuild advice).
    - An image built before this item has no such file. It reads as a difference, which is right: it is an old image.
    - "No source tree" is unchanged, and `restore` is not gated.
    - Reason: row 133's principle, "an old image never has a reason to migrate", holds for its libraries too. Seed and
      Alembic run with them.
    - `pyproject.toml` is not compared. Its dependency content is already in `image.txt` through the guard, and a
      tool-settings edit should not force a rebuild.

13. **Frontend: already locked, one CI alignment.**
    - `npm ci` with `package-lock.json` in the Dockerfile and in CI is the same lock used alike, with integrity hashes
      and every platform's optional packages. `npm ci` refusing a mismatched `package.json` is the guard. The e2e
      image does the same with its own lock.
    - The one change: the CI `frontend` job's `node-version` becomes exactly `"22.23.3"`, the image's version, and
      the test checks equality instead of the major.
    - Developers use `npm ci` to stay in step and `npm install <pkg>@<version>` only for a deliberate upgrade that
      commits the lock. This rule is written in operations.md.
    - Refused: a separate npm guard. It would add nothing to `npm ci`.

14. **How a refresh is tested.** A refresh is an ordinary commit that changes `uv.lock` and both exports, so it gets
    the full CI run:
    - `backend` installs the new `dev.txt` and runs ruff, the guard and pytest;
    - `compose` builds every backend image from the new `image.txt` with `pip check` and the import smoke.
    Deploying it is the normal rebuild (operations.md section 6), with no extra step. Refused: a cooldown that refuses
    releases younger than N days. The lock plus CI already stop an untested version from reaching an image.

15. **Secret scanning.** `uv.lock` and the exports hold sha256 hashes and PyPI file URLs only. If the pinned gitleaks
    flags them, the developer adds one commented allowlist entry per path to `.gitleaks.toml`, as was done for
    `frontend/package-lock.json`. Nothing is allowed in advance.

No deviation from the plan: the plan is silent on dependency management, and CLAUDE.md asks for `ruff check` clean and
`pytest -q` green, which this keeps.

## Data
None. No table, column or reference code; no migration.

## Services
- `backend/aslms/services/source_check.py`: `image_matches_source()` gains the lock comparison of decision 12. It uses
  a file digest helper next to `tree_digest()` (None when the file is missing), the message part "dependency lock
  differs", and docstring and module text naming the third comparison. `REBUILD` is unchanged.
- `backend/tools/deps.py` (new, not in the image): the commands `lock`, `check` and `sync` of decisions 7 and 8. The
  uv and pip command lines are built by pure functions so they can be unit-tested without the network. It is
  stdlib-only and prints no environment values.
- `backend/pyproject.toml`:
  - `uv` in the `dev` extra;
  - `[dependency-groups] build = ["setuptools>=68"]`;
  - `[tool.uv]` with `environments` and `required-environments`;
  - the kombu cap lifted and the comments rewritten (decision 11).
- `backend/uv.lock`, `backend/requirements/image.txt`, `backend/requirements/dev.txt` (new, generated).
- `backend/Dockerfile`: decision 5's order and flags, `pip check`, the import smoke (decision 6) and header comments
  naming this design.
- `backend/constraints-ci.txt`: deleted.
- `.github/workflows/ci.yml`:
  - the `backend` install and the "Lock up to date" step;
  - the pip cache keyed on `dev.txt`;
  - `python-version` `"3.12.15"`;
  - `node-version` `"22.23.3"`;
  - the comment that names `constraints-ci.txt` removed.
- `docs/operations.md`:
  - section 19's `backend` row (installed from `requirements/dev.txt`, the lock check);
  - section 16 (`deps.py sync` after any lock change, `npm ci` for the frontend);
  - section 6 (images install exactly the lock; a lock refresh is deployed by the normal rebuild);
  - section 8 (the lock is part of what "pinned" means);
  - a new section 23, "Dependencies and the lock": the files, the refresh command and its three forms, how CI tests
    a refresh, the platforms, the `.venv`.
- `docs/hosting-guide/build.js`: the `migrate` exit-5 sentence (section 8.2) also names a different dependency lock.
  Regenerate `ASLMS_Hosting_Guide.docx` with a revision row. The Software Documentation is updated only if it
  describes how the backend image installs its packages (the developer checks).
- No audit row: this changes no significant action, and no application behaviour.

## API
None. No endpoint, no `Permission`.

## Jobs
None.

## Tests
New `backend/tests/unit/test_dependency_lock.py` (offline, no network):
- `test_lock_records_the_pyproject_requirements`: the project's recorded requirements in `uv.lock` (dependencies,
  the `dev` and `redis` extras, the `build` group) equal `pyproject.toml`'s, compared as parsed requirements. This
  is the offline half of the guard.
- `test_exports_are_pinned_and_hashed`: every requirement in `image.txt` and `dev.txt` is `==` with at least one
  `--hash=sha256:`. There is no `-e`, no URL, no `-c` and no line for `aslms`.
- `test_image_set_is_inside_the_ci_set_with_the_same_versions`: every package of `image.txt` is in `dev.txt` at the
  same version with the same markers.
- `test_every_direct_requirement_is_exported_and_satisfied`: each runtime requirement and the `redis` extra are in
  `image.txt`, and each `dev` requirement is in `dev.txt`, at a version inside the `pyproject.toml` specifier.
- `test_packaging_is_a_runtime_dependency`: `packaging` is in `image.txt` (decision 11).
- `test_lock_has_wheels_for_linux_and_windows`: each locked package applicable to the platform has, in `uv.lock`, a
  pure wheel or a wheel matching Linux x86_64 CPython 3.12 (manylinux or abi3) and Windows AMD64 CPython 3.13. This
  is checked on the image's and the `.venv`'s interpreters, not on every allowed one.
- `test_installed_versions_match_the_lock`: in the running environment, every `dev.txt` requirement whose markers
  apply is installed at its pinned version. On a stale `.venv` it fails, naming the packages and
  `python tools/deps.py sync`.
- `test_constraints_ci_is_retired`: `backend/constraints-ci.txt` does not exist and no workflow names it.
- `test_dockerfile_installs_only_from_the_lock`:
  - `requirements/image.txt` is copied before `aslms`;
  - it is installed with `--require-hashes` and `--only-binary :all:`;
  - the project is installed with `--no-deps --no-build-isolation`;
  - `pip check` runs;
  - the smoke imports `kombu.transport.redis`, `aslms.jobs.celery_app`, `aslms.api.main` and `aslms.cli.main`;
  - no `pip install ".[` without `--no-deps` remains.

New `backend/tests/unit/test_deps_tool.py`:
- `test_lock_command_builds_uv_lock_then_both_exports`: plain, `--upgrade` and `--upgrade-package kombu`, with the
  exact export flags (`--frozen`, `--no-emit-project`, the extras and group, the output paths).
- `test_check_names_the_stale_file_and_the_fix`: with a fake runner, a different export, or a failed
  `uv lock --locked`, exits 1 and names the file and `deps.py lock`.
- `test_sync_installs_hash_checked_then_the_project`: the pip command lines of decision 8.
- `test_sync_prunes_only_what_the_lock_does_not_name_for_this_platform`: never `pip` or `aslms`, and a
  marker-excluded package (`uvloop` on Windows) is not "missing".

Changed `backend/tests/unit/test_ci_workflow.py`:
- `test_backend_requires_the_database` checks the new install lines, `pip check` and the `deps.py check` step; the
  cache path is `dev.txt`.
- `test_python_version_matches_the_backend_image` and `test_node_version_matches_the_portal_image` compare exact
  versions (decisions 9 and 13).

Changed `backend/tests/unit/test_migrate_source_check.py`:
- `test_identical_trees_and_locks_pass`.
- `test_a_lock_only_difference_is_exit_5`: the message has "dependency lock differs" and not "aslms package".
- `test_an_image_without_a_lock_file_is_old`.
- The existing no-source case is unchanged.

## Verification
Developer and tester (no shared stack is touched; temporary names only):
1. In the `.venv`:
   - `python tools/deps.py check` is clean;
   - `python tools/deps.py sync`, then `sync --check`, is clean;
   - `ruff check .`, `ruff format --check .` and `pytest -q` are green.
   `sync` reports no version change for any package of `constraints-ci.txt` (decision 4); it adds `uv` and
   `setuptools` and removes nothing but leftovers.
2. A second plain `python tools/deps.py lock` leaves `git status` clean (the lock is stable).
3. The guard bites: a temporary edit adds a requirement to `pyproject.toml` with no refresh. `deps.py check` exits 1
   naming `uv.lock`, and `test_lock_records_the_pyproject_requirements` fails. Then revert.
4. The incident is caught: in a throwaway `python:3.12.15-slim` container,
   `pip install kombu==5.7.0 redis && python -c "import kombu.transport.redis"` fails with
   `ModuleNotFoundError: packaging`. This shows that the import smoke would have stopped the 14:20 build.
5. The CI `backend` job reproduced in Linux, as in github-and-ci Verification step 4, on a private network:
   - a `postgres:16.15` container named `pg-dl` on network `dl-check`;
   - in `python:3.12.15-slim` with `./backend` mounted, run:
     ```
     pip install --require-hashes --only-binary :all: -r requirements/dev.txt
     pip install --no-deps --no-build-isolation -e .
     pip check
     python tools/deps.py check
     ruff check .
     ruff format --check .
     pytest -q
     ```
   It is green; then remove `pg-dl` and the network.
6. The image on a temporary tag:
   - `docker build -t tmpdl-backend backend/` passes `pip check` and the smoke;
   - `docker run --rm --entrypoint pip tmpdl-backend freeze` equals the Linux lines of `image.txt` (a script compares
     name and version);
   - against the current `aslms-api:latest` it shows the 27 expected version changes of decision 4 and `setuptools` added (the `build` group), and no others;
   - `docker image rm tmpdl-backend`.
7. `npm ci` in `frontend/` succeeds with no change to `package-lock.json`. gitleaks (pinned image, repository
   configuration) on the branch is clean, with allowlist entries only if flagged, each commented.

CI (after the integrator's push): `changes`, `policy`, `backend`, `frontend`, `compose` and `ci-ok` are green, with the
backend job's "Lock up to date" step passing. The run address is recorded in the cycle report.

Deploy (the main session's, not run by the team agents; no migration, no backup step needed):
1. From a clean worktree of `main`, build these:
   - `docker compose build`;
   - `docker compose --profile ops build migrate`;
   - `docker compose --profile monitoring build ops-exporter`, when the monitoring profile is in use.
2. Recreate `api`, `worker`, `scheduler` and `backup` with `--no-deps --force-recreate`, carrying the court-data switch
   on that `up`. Then check the switch in `api` and `worker` (runbook section 11).
3. Check:
   - the scheduler log shows beat started, with no restart loop;
   - worker liveness is fresh on the System Health screen;
   - the api health answers;
   - `docker run --rm --entrypoint pip aslms-api freeze` matches `image.txt`.
4. `docker compose --profile ops run --rm migrate` is not needed (no migration). The next time it runs, it compares the
   lock too.
5. The owner's `.venv`: run `python tools/deps.py sync` once after the merge.

## Open questions
None. For the owner's attention at approval (not blocking): decision 4 moves the running images back to the tested
versions (27 packages, among them fastapi 0.162.0 to 0.142.2 and python-dateutil 4.0.0 to 2.9.0.post0), and an upgrade
to current releases becomes a separate refresh row.

## Deviations
- Decision 1, the export header: `deps.py` runs `uv export --no-header` and writes its own first line, "Generated from
  backend/uv.lock by `python tools/deps.py lock` ... Do not edit by hand.", so the file names its refresh command and
  does not carry uv's command line. uv's output is taken with LF line ends (`.gitattributes` already keeps LF), and
  `deps.py check` compares those bytes with the committed files.
- Decision 2: uv 0.13.7 (current on 5 Nov 2026), so the `dev` extra says `uv>=0.13.7`. Decision 3: setuptools 84.2.1
  (current); it builds the wheel (image) and the editable install (`.venv`) alone with `--no-build-isolation`.
- Decision 4: the first lock also holds `async-timeout` 5.0.1, which redis needs only on Python below 3.11.3 (marker
  `python_full_version < '3.11.3'`). The Windows freeze could not name it, and none of the image, CI or the `.venv`
  installs it. After the one-off constraints were removed, two plain `deps.py lock` runs left `uv.lock` byte-identical.
- Decision 4, the owner's attention figure: measured on 5 Nov 2026 against the current `aslms-api:latest` (rebuilt
  since 3 Nov, so newer than the Context table, e.g. psycopg 3.3.8 and sqlalchemy 2.1.8), the locked image changes 28
  package versions back to the tested set and adds two packages: `setuptools` 84.2.1 (the `build` group) and `six`
  1.17.0, which python-dateutil 2.9.0.post0 needs and 4.0.0 had dropped. Nothing else changes; the new image's
  `pip freeze` equals the Linux lines of `image.txt`.
- Decision 6: the import smoke needed no setting beyond `APP_ENV=test`; no placeholder was added.
- Decision 8, `sync`: the markers are read with the installed `packaging`, or pip's own vendored copy when it is
  absent, so the script stays standard library plus pip. `sync --check` names a half-removed `~name` folder as a note
  but does not fail on it, since it is not an installed package and pip cannot remove it (the `.venv` holds
  `~slms-3.0.0a0.dist-info`; delete the folder by hand). The first `sync` in the `.venv` added `setuptools` (and `uv`,
  installed just before to make the first lock), changed no version of `constraints-ci.txt` and removed nothing.
- Decision 9: `required-environments` worked as written over the allowed Pythons; no narrowing. `actions/setup-python`
  lists 3.12.15 for ubuntu 22.04, 24.04 and 26.04, so CI asks for exactly `"3.12.15"`.
- Tests: two beyond the design, `test_a_failed_uv_lock_writes_no_export` and
  `test_sync_check_reports_and_fails_on_a_difference` (`test_deps_tool.py`).
- Hosting guide: `ASLMS_Hosting_Guide.docx` regenerated as 1.3 with the revision row; `toc.json` (contents page
  numbers from a rendered PDF) was not refreshed, as no PDF renderer is installed here. The Software Documentation does
  not describe how the backend image installs its packages, so it is unchanged.
- Decision 15: the pinned gitleaks found nothing in `uv.lock`, the exports or `tools/deps.py`; `.gitleaks.toml` is
  unchanged.
