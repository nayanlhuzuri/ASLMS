# Definition of done (one backlog item)

A feature is done when every line below holds on the feature branch; the integrator checks them before the
merge and the reviewer treats a miss as a blocking finding.

**Code**
- `ruff check` clean and `ruff format` applied; `pytest -q` green, including the database tests.
- Every new table or column is in `docs/schema/schema.md` *before* the migration that adds it; the migration
  is new (applied ones are never edited), its downgrade works, and `test_database_matches_the_models` passes.
- Every new service or endpoint has tests: the happy path, the negative paths, and for anything that reads
  case data a visibility test (a user outside the scope gets nothing).
- Every significant action (ownership, custody, notes, uploads, users, access, configuration) writes an
  `audit_log` row and, where the timeline needs it, an event; tests assert the rows.
- No identifier is fabricated (a case without a CNR stays provisional); no NAPIX call outside
  `backend/aslms/integration/napix/`; nothing copied from `ASLMS-legacy`.
- Secrets stay in `.env`; nothing is logged that came from it.

**Documents**
- The decisions log has an entry for the feature: what was built, decisions, deviations from the plan and why.
- `CLAUDE.md` "Current focus" names the next step; the backlog row is `done` with the report linked.
- `.env.example` and `compose.yml` carry any new variable or service.

**Process**
- The design note exists and was approved by the owner before building; deviations are written back into it.
- Review findings are closed (fixed) or recorded as advisory in the report with the reason.
- The branch is squash-merged into `main` with the attribution footer and tagged `feature/<slug>-done`.
