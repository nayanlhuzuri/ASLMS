# Report: dashboard-my-work-polish (row 228)

Date: 2026-11-11. Branch `feature/dashboard-my-work-polish`, squash-merged into `main` (436a615), tag `feature/dashboard-my-work-polish-done`.

## What changed
The dashboard's "More About My Work" section (`frontend/src/components/dashboard/Blocks.tsx`): three cards with one
heading style and a View All link each (Case Inbox, Alerts); alerts in aligned columns (type, what happened, date
raised) with the case number once; badge colours with fixed meanings (hearing alerts on the hearing-date bands,
recommendations navy, strong solid and possible outlined); the date raised, newest first; "Hearing Due" in Title Case;
My Cases with department names; Cases with Me with one Due column. Kit: Badge look (solid, outline) and a HearingDate
label. Backend: additive read-only fields on `GET /dashboard/me` (`schemas.py`, `services/dashboard.py`,
`services/alert_rules.py`), `openapi.json` and generated types regenerated. No migration, no table, no new endpoint.
The decisions-log entry and the backlog row exist; design note status `approved`.
The squash merge conflicted in `CLAUDE.md` "Current focus" (row 231's deployed text on main against row 228's
sentence on the branch); both kept, row 228 removed from the next-builds list.

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3219 passed, 3 skipped (44 min).
- `docker compose build`: succeeded (api, init, scheduler, web, pgbouncer built).
- Screen check on a private network against a `web` image built from the branch (runbook section 16): 174 routes and
  states, 419 screenshots, 0 findings, 281 s; 575 passed, 7 skipped. Temporary containers, network and images removed;
  the shared stack was not touched.
- CI on `main` before the merge: success (run 42875073185).
- `git status` clean on the branch.

## Pushed commit and CI
See the Finishing answer of the cycle: the push of `main` and the tag follows this commit; the CI run address is
recorded there.

## Review findings
- Advisory (the `figure` helper turns a null `counsel_active` into 0, where main showed a dash, so a department where
  the person is not standing counsel reads as zero active cases): not closed here; filed as row 240.

## Deviations
None.

## Follow-ups
- Row 240 `dashboard-my-work-polish-followups` (the advisory above).

## Load status
`aslms queue-status` was started but did not answer within two minutes; not recorded for this frontend-only cycle.

## Deployed
11 Nov 2026 at 03:12 IST, images built from clean `main` (6d9daa8) after CI run 42901933984 passed. No migration. `docker compose --profile monitoring up -d --wait` with the court-data switch, then `api`, `worker`, `scheduler` and `web` recreated with `--no-deps --force-recreate`. The switch reads `true` in `api` and `worker`, mail goes to Mailpit, the web build ID matches the image (`lh6Xr-enHXPJUeQaNiQWN`), and `portal_smoke.py` passed.
