# How the ASLMS team works

The application is built by a team of specialised agents running inside Claude Code, on a loop: an architect
designs the next backlog item, a developer builds it on a branch, a tester hardens the tests, a reviewer
checks the work against the project's rules, a scribe keeps the documents, and an integrator merges. The
owner approves each design; everything after that runs unattended. The team is defined in this repository
(`.claude/agents`, `.claude/skills`, `.claude/workflows`, `.claude/settings.json`) and changes to it are
reviewed like code.

## Roles

| Agent | What it does | Writes |
|---|---|---|
| `architect` | Turns a backlog item into a design note: context, decisions, schema changes, services, API, tests, open questions. Never invents a business rule or an API field; when one is missing the note is `blocked` with the question. | `docs/design/<slug>.md` |
| `developer` | Builds the approved design on `feature/<slug>` in small commits, tests with the code, `ruff` and `pytest` green before each commit. | code, tests, migrations |
| `tester` | Adds the tests the design asks for and the ones the developer missed (negative paths, visibility, audit rows, idempotence, migration cycle); runs the suite; returns gaps. | tests |
| `reviewer` | Reviews the branch diff against `CLAUDE.md`, `DB_STANDARD.md`, the design note and security; findings are `blocking` or `advisory`, each with a failure scenario. | review findings (in the cycle report) |
| `scribe` | Appends the decisions-log entry, the as-built lines in `schema.md`, the backlog status and the "Current focus" block of `CLAUDE.md`. | docs |
| `integrator` | Final gates (`ruff check`, `pytest -q`, `docker compose build`), squash-merge into `main`, tag, cycle report. | `main`, `docs/reports/<date>-<slug>.md` |
| `security-auditor` | Outside the cycle, on request: an independent cyber security audit of the whole application (authentication, the backend-for-frontend, access control, injection, files, SSRF, NAPIX, the assistant, headers, infrastructure, supply chain). Read-only; proves findings with local tests against the test database; never touches live data, `.env` or NAPIX. | `docs/audits/<date>-security-audit.md` |

## The cycle

```
pick → design → [owner approves] → build → test ⇄ fix → review ⇄ fix → docs → merge → report
```

1. `/team-cycle` takes the top `todo` item of `docs/backlog.md` (or the slug given).
2. The architect writes the design note. Status `awaiting-approval` stops the cycle; `blocked` stops it with
   a question for the owner.
3. The owner reads `docs/design/<slug>.md` and runs `/team-approve <slug>` (or edits the note and re-runs
   `/team-design <slug>`).
4. The next `/team-cycle` builds, tests, reviews, documents and merges without further questions. Up to two
   test rounds and three review rounds; unresolved blocking findings stop the cycle with the report.
5. The cycle report lands in `docs/reports/`; the backlog row becomes `done`.

Continuous operation: `/loop 45m /team-cycle` keeps cycling while a Claude Code session is open. A tick with
nothing to do (waiting for approval) is a no-op. There is no server-side scheduler (it would need an AI API key
in GitHub; the owner's decision later).

**Remote and CI** (design github-and-ci): the code lives in the private repository `nayanlhuzuri/aslms` once the
owner has made the first push (operations.md section 19). The team keeps merging locally; after each merge the
integrator pushes `main` and the `feature/<slug>-done` tag (fast-forward only, never forced). GitHub Actions
(`.github/workflows/ci.yml`) runs the gates on every push of `main` and every pull request: repository policy and
gitleaks, ruff and pytest against a Postgres service, the portal checks, the Compose build with the `web` smoke and
`promtool`. A red run on `main` stops the next merge. The guard hook refuses forced pushes, remote changes and
`gh secret` / `gh api` / `gh repo`; the remote and the repository's settings are the owner's.

## Commands

| Command | Does |
|---|---|
| `/team-cycle [slug]` | One full cycle for the top backlog item or the named one |
| `/team-design <slug>` | The architect only; produces or refreshes the design note |
| `/team-approve <slug>` | Marks the design approved (note, backlog, decisions log) |
| `/team-review` | The reviewer alone on the current branch |
| `/security-audit [scope]` | The security auditor on `main`: a vulnerability report with severity, exploit scenario and fix |
| `/team-status` | Backlog, open design notes, branches, last reports, load progress |

## Guardrails (hooks in `.claude/settings.json`, enforced by the harness, not by prompts)

- No agent can read or write `.env` or any `.env.*` other than `.env.example`.
- Applied migrations under `backend/migrations/versions/` cannot be edited; schema changes are new migrations.
- `NAPIX_ENABLED=true` cannot be written into any file; the live switch is passed on the command line by the
  owner for that run only.
- Nothing under `D:\Dev Workspace\ASLMS-legacy` can be edited, copied or imported.
- Every edited Python file is formatted and linted on save.

## Where things are

- Backlog: `docs/backlog.md` (the owner reorders it; the team takes the top `todo`).
- Design notes: `docs/design/<slug>.md` (template: `docs/team/design-template.md`).
- Reports: `docs/reports/<date>-<slug>.md`.
- Decisions: `docs/claude_ASLMS_design_decisions.md` (append-only history).
- Definition of done: `docs/team/definition-of-done.md`.

## Stopping and intervening

Stop the loop with `/loop` (no arguments) or by closing the session; a cycle in progress leaves its branch
behind and the next cycle resumes from the backlog status. To take a feature back by hand: set its status to
`todo`, delete or keep the branch, and edit the design note.
