# Cycle report: recommend-and-claim (2026-10-04)

Design: `docs/design/recommend-and-claim.md` (approved by the owner on 2026-10-04 after one review round:
scoring editable by the super admin, claimed cases never return to the pool, take-over within the department).
Branch `feature/recommend-and-claim`, squash-merged into `main`; tag `feature/recommend-and-claim-done`.

## What changed (40 files, +8,012 / −43)
- **Migration 0004** `ownership_rules`: `scoring_settings` (versioned; weights and the two band thresholds),
  partial unique indexes (one active primary per case, one active row per case and office, one active
  recommendation per case and office, one open transfer per case), CHECK constraints on weights and scores and
  on "a primary row is never released", new columns on `case_ownership` (`allotted_at`, `allotted_by_user_id`,
  `release_reason`) and `ownership_transfers` (`decision_note`, `stay_as_watcher`); rule weights become nullable
  overrides.
- **Services**: `scoring_settings` (versioned saves with reason, optimistic locking, audit, `config_changed`
  event, rescore on save), `matching` (the engine: counsel codes, keywords, name patterns, watchlist, linked
  cases; strongest signal per kind combined as 1 − Π(1 − w); engine version `<engine>.<settings version>`;
  inline scoring after cause-list entries and dossiers inside a savepoint; dirty rescore), `matching_rules`
  (rule administration in the actor's office subtree, generic State codes by the super admin only),
  `ownership` (claim, dismiss, suggest elsewhere, allot, take over, stop watching, transfer request / accept /
  decline / withdraw; row locks), `custody` (moves for claimed, allotted, taken_over, transferred), `inbox`
  (Recommended, Claimed with Active / Disposed, Unclaimed pool, Transfers, Counts), `visibility`
  (`department_of`, `owned_case_filter`), `cases.resolve_case_ref` (id, ref_no or CNR).
- **API**: `/admin/scoring-settings` (+ history), `/admin/counsel-codes` (+ `/unmapped`), `/admin/keywords`,
  `/admin/name-patterns`, `/admin/watchlist`, `/admin/matching/cases/{ref}/scores`, `/inbox/*`,
  `/cases/{ref}/ownership`, `POST /cases/{ref}/claim | dismiss | suggest | allot | take-over | stop-watching |
  transfers`, `/transfers/{trf}/accept | decline | withdraw`.
- **Jobs and CLI**: Celery task `aslms.rescore_if_dirty`, beat every 15 minutes; `aslms rescore [--all | --case
  REF]`, `aslms codes unmapped`.
- **Functions**: `admin.scoring` (super admin only by default), `cases.take_over` (department types);
  `cases.release` relabelled "Stop watching"; event type `case_taken_over`.
- **Docs**: schema.md group 5 as built, decisions-log entry, design note "Deviations" section, backlog.

## Gates
- `ruff check` clean; `pytest -q` 220 passed (150 before the cycle); `docker compose build` ok.
- The database tests prove: seed inserts scoring settings version 1 once; the migration cycles; the model diff
  is empty; engine writes produce no audit rows; refused actions leave no audit row or event; a disabled user
  gets 401 on the inbox and ownership endpoints; unknown references and missing functions are 404 / 403.

## Review (reviewer, one round): 8 advisory findings, no blocking finding, cleared to merge
Closed in this cycle:
- CLAUDE.md states the 0.85 / 0.50 bands as fixed rules → the owner reworded CLAUDE.md on `main` (`e5d23d7`).

Carried to backlog row 20 `recommend-and-claim-hardening` (none loses or exposes data; each is a sharpening):
1. `last_rescore_start` counts only `succeeded` runs, so one case that always fails keeps the rules "dirty" and
   every 15-minute tick rescores everything.
2. The dirty check compares rule `updated_at` (transaction start) with the run's `started_at`; an edit that
   commits after the run loaded the rules is missed until another rule changes.
3. `apply_scores` reads a case's owners without the row lock `claim` takes; a rescore concurrent with a claim
   can open a recommendation for the department that just claimed.
4. Regex name patterns are not guarded against catastrophic backtracking (Python `re` has no timeout); a bad
   pattern could stall ingestion. Fix: a bounded regex engine or a complexity check at save time.
5. `RuleSet.load` runs outside the per-case savepoint, so a failure loading rules fails the cause-list or
   dossier item instead of being recorded in `source_failures`.
6. Accepting a transfer promotes the target's watcher row but moves custody to the bare department, losing the
   allotted officer for alerts.
7. Rule list endpoints return every row without `limit` / `offset`, contrary to the design's API section.

## Deviations recorded in the design note
See "Deviations" in `docs/design/recommend-and-claim.md` (written by the developer during the build).

## Process notes
- The build was interrupted once by a network error to the API (not a usage limit); the developer had committed
  two clean commits, the cycle was resumed and continued from them.
- The integrator completed every gate but the permission system refused its `git commit` of the squash merge
  on `main`; the merge, tag, report and backlog update were completed by the lead in the session. Follow-up: the
  allowlist needs `Bash(git commit*)` honoured for the integrator's heredoc form, or the integrator commits with
  `-F` from a file.
- Live walk-through of the design's verification steps 3–13 against the loaded January 2025 days was not run in
  this cycle; it belongs to the deployment checklist.

## Load status
Not sampled in this cycle (the Compose worker keeps running; see `aslms queue-status`).
