# Order sections (row 250), integrator report

Merged 16 Nov 2026 as one squash commit on `main`, tag `feature/order-sections-done`. Design: `docs/design/order-sections.md` (approved 15 Nov 2026).

## What changed
- Rule-based order reader `backend/aslms/services/order_parse.py` (no AI, no court call): header, parts, facts, outcome, linked cases, layout flag.
- Derived table `order_sections` (migration 0038), with page and offsets of every part, the PDF's SHA-256 and the parser version; rows are never changed.
- 5-minute job and `aslms orders` (`backend/aslms/services/order_sections.py`), setting `ORDER_SECTIONS_BATCH`.
- API: the reading on the Orders list, the sections route, the Order Reading Checks block of data-health.
- Portal: What the Order Says on the Orders tab (`OrderSays.tsx`, `Orders.tsx`), Order Reading Checks on Data Collection.
- Docs: decisions log, runbook section 25, workflows, both Word guides (Annexure E).

## Gates
- `ruff check .`: All checks passed.
- `pytest -q`: 3607 passed, 3 skipped, 282 warnings in 58m17s.
- `docker compose build`: succeeded (shared stack not touched, no `up`).
- Screen check (private network, temporary images, runbook section 16): 183 routes and states, 590 screenshots, 0 findings, 389 s.
- CI on `main` before the merge: latest run success (secret scan, 16 Nov 00:31 UTC).
- `git status` clean on the branch; design status `approved`; decisions-log entry and backlog row present.

## Review findings
- Blocking, backfill never ending on a failing order: closed in fccfff5 (failing orders come last, the backfill ends).
- Blocking, `whole` readings keeping cause title, advocates and coram spans: closed in 10cd322.
- Advisories: the rest are left open and recorded in backlog row 264 (data-health isolation, the 5-minute job's scans, re-extraction by `text_sha256`, "Not Read Yet" state, design-note measurements, linked-case spans and page map, the `can_view_document` test, repeated failure logging). Row 263 holds the scribe's follow-ups.

## Deviations
None beyond those recorded in the design note.

## Deploy (not done here)
Apply 0038 with the `migrate` step in a late-night window, `docker compose build`, then `docker compose exec api aslms orders parse --backfill` once (runbook section 25); the owner's sample of 20 orders is row 263.

## Follow-up rows
264 (review advisories). 263 already existed.

## Load status (`aslms queue-status`, 16 Nov 2026)
masters done 1; order_pdf done 265,584, pending 129,928, skipped 80; status_batch done 3,662, skipped 9.

## Deploy
Deployed 17 Nov 2026 together with row 264 (owner's confirmation (d) of row 264), from `main` at 716b001 after CI was
green (the compose job's first try lost its network during `npm ci` and passed on a rerun).
- 23:00 IST: `api`, `worker`, `worker2`, `scheduler`, `web` and `pgbouncer` stopped; `napix_call_log` held 579,170 rows.
- `docker compose --profile ops run --rm migrate`: preflight passed (dev, 7 warnings), backup
  `20261117-2300-pre-migrate` written and listed by `pg_restore`, 0037 -> 0038, seed nothing to insert, audit row
  `system.migrated`. Done at 23:28.
- `up -d` with the court-data switch, then `--no-deps --force-recreate api worker worker2 scheduler web`: the switch on
  in `api`, `worker` and `worker2`, both workers "NAPIX on", `/signin` 307, `/api/health` 200, the running web
  `BUILD_ID` equals the image's. Portal down 23:00 to 23:29.
- `aslms orders parse --dry-run --limit 3000`: 2,967 template, 33 whole, no failure, 1.98 s per 1,000.
- `aslms orders parse --backfill` 23:30 to 23:53: 269,999 read at version 2, 0 failed. `aslms orders status`:
  `parser_version` 2, `read` = `orders_with_text` = 269,999, `waiting` 0, `failed` 0, `timed_out` empty. No version 1
  row. No court call from the backfill (the 904 calls in the window were the queue's CNR fetches).
- Measurements (table 672 MB, the times of decision 14, all inside budget) are in `docs/design/order-sections.md`,
  "Measurements".
