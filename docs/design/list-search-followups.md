# Design: List search follow-ups (row 175 review advisories)

```
slug: list-search-followups
status: awaiting-approval
author: architect
date: 2026-10-30
approved_by: —
```

## Context
Backlog row 201. The row 175 review (`docs/reports/2026-10-28-list-search.md`, "Review") left three advisories on the
approved design `docs/design/list-search.md` (decisions 6, 9 to 12 and 41). All three were checked against `main`
(eeb3424) on 30 Oct 2026; none is fixed yet, none is dropped.

1. **The rescore can miss a mapping saved during a run.** `services/matching.py` decides "dirty" by comparing rule
   timestamps with the start of the last succeeded `rescore` run: `claim_rescore` (lines 1034-1055) calls
   `rules_changed_since(s, last_rescore_start(s))` (944-961), and `rescore_if_dirty` (1058-1079) asks
   `rules_changed_since(s, started)` after its run (1071-1073). `job_runs.started_at` defaults to `now()`, the claim
   transaction's start (`domain/ops.py:72`). Race: a mapping save whose transaction began before the claim and committed
   after `RuleSet.load` (line 980) carries an `updated_at` older than the run's start, so the run does not see it, the
   follow-up is not dispatched, and every later claim also says "clean" until an unrelated change.
   - **The review's suggested fix does not close the race.** It proposes taking the cut-off with `clock_timestamp()`
     just before `RuleSet.load`. But `updated_at` is written by the trigger `set_updated_at()` as `now()`, the *saving*
     transaction's start (`migrations/versions/0001_core.py:332-333`), and `created_at` defaults to `now()`
     (`db/base.py:147-155`). A save whose transaction started before any cut-off keeps a timestamp older than that
     cut-off whatever clock the cut-off is read from, and a row updated but not yet committed is invisible to the load
     either way. No timestamp comparison can tell "committed after the load" apart. Decision 1 replaces it.
2. **`GET /admin/counsel-codes` accepts any `q`.** The router (`api/routers/matching.py:301-320`) passes `q` straight
   to `matching_rules._counsel_codes_stmt` (`services/matching_rules.py:324-327`), which only normalises it. Design
   decision 6 asks every non-case list for 2 to 100 characters with 400 `bad_q` (`services/list_search.parse`, lines
   93-103), as `GET /admin/counsel-codes/unmapped/page` already does (`services/matching.py:1316`). A one-letter or
   1,000-character `q` is accepted today; a blank `q` of spaces is treated as a search that matches everything and sets
   `total_all`.
3. **A deactivated code does not return to Recommended From Cause Lists.** `saved()` in
   `frontend/src/components/admin/mapping/CounselCodes.tsx:97-102` handles every save the same way: it drops the code
   from the loaded pages of the unmapped panel (`dropMapped`) and refreshes the codes list. The row menu calls it for
   Deactivate too (`RuleMenu` `onDone`, line 145; `common.tsx:123` passes `"status" | "office"`). A deactivated code
   is unmapped again, but the panel's query (`staleTime` 10 minutes, line 316) is never refetched, and `dropMapped`
   even removes it if it was there. The code reappears only after a reload or ten minutes.

Not covered: the same 2-to-100 check on other list endpoints (each already parses `q`, checked: only the two
counsel-code reads take a `q` in `api/routers/matching.py`); a `maxLength` on the kit's `ListSearch` (portal-wide, not
asked); rounds 2 to 4 of list search (rows 179 to 181).

## Decisions
1. **"Dirty" is decided by a fingerprint of the rules, recorded by each run, not by timestamps.**
   - A new `matching.rules_fingerprint(session) -> str`: one SQL statement over the six `RULE_TABLES`
     (`CounselCode`, `OfficeKeyword`, `OfficeNamePattern`, `OfficeWatchlist`, `Office`, `ScoringSettings`, line 941):
     for each table `count(*)` and `md5(string_agg(id::text || '@' || updated_at::text, ',' ORDER BY id))`, joined in
     table order and hashed once more with `md5`. Every insert and every update changes it (`updated_at` moves on
     every UPDATE through the trigger; nothing in these tables is deleted). The tables hold hundreds of rows, so the
     statement is cheap.
   - `rescore_all` reads the fingerprint in the same session, **immediately before** `RuleSet.load` (line 980), and
     keeps it on the report: `ScoreReport.rules_fingerprint: str | None`, written into `job_runs.counters` by
     `as_dict` (key `rules_fingerprint`). Read before the load, so a save committing between the two statements makes
     the stored fingerprint older than the rules used: the worst case is one extra rescore, never a missed one.
   - A new `matching.rules_dirty(session) -> bool` replaces the check in `claim_rescore` (line 1049): no succeeded
     `rescore` run → dirty; the latest succeeded run (by `started_at`) has no `rules_fingerprint` (a run from before
     this change) → the old `rules_changed_since(s, its started_at)`, so the first claim after deploy does not start a
     surprise full rescore; otherwise dirty when `rules_fingerprint(s)` differs from the stored one.
   - `rescore_if_dirty` decides the follow-up by `rules_fingerprint(s) != report.rules_fingerprint` in place of lines
     1071-1073. The single-flight claim, the 30-minute window, the advisory lock and `dispatch` are unchanged.
   - `rules_changed_since` and `last_rescore_start` stay for the fallback.
   - Alternatives: the review's `clock_timestamp()` cut-off (does not work, Context 1); a Redis "pending" flag set by
     a refused claim (needs the same commit-ordering argument plus a second store, and the beat path has no flag);
     comparing `xmin` with a stored snapshot (`xid` to `xid8` conversion and wraparound handling for no gain).
2. **`GET /admin/counsel-codes` validates `q` with `list_search.parse`.** `_counsel_codes_stmt` calls
   `list_search.parse(q)` first; `None` (absent or only spaces) means no search; otherwise the trimmed raw text is
   normalised with `normalise_counsel_code` and matched as today (wildcards literal). A `ListSearchError` raises 400
   `bad_q` through `api.errors.list_error`, the same message as the unmapped page ("Type at least 2 letters." / "A
   search is at most 100 characters."). The router sets `total_all` only when a search was applied (not for a blank
   `q`) and declares `responses={400: {"model": schemas.ErrorOut}}`, so `frontend/openapi.json` and
   `lib/api/schema.d.ts` are regenerated (`gen:api`). The portal already never sends fewer than 2 characters
   (`minChars={2}`, `useListState` line 78), so no screen changes.
3. **A deactivated code makes the panel read again; any other save keeps the local drop.** `saved(row)` becomes:
   - `row.is_active` (a new mapping, a reactivation, an office move): today's `dropMapped`, no request;
   - `!row.is_active` (Deactivate): `queryClient.resetQueries({ queryKey: UNMAPPED_KEY })`, so the panel loads its
     first page again and the code appears wherever the server sorts it.
   - `resetQueries`, not `invalidateQueries`: invalidating an infinite query refetches every loaded page in turn, and
     each page recomputes the whole unmapped aggregate over the current cause lists on the server
     (`_unmapped_aggregate`, `services/matching.py:1103-1147`). A deactivation is rare; going back to the first page is
     acceptable. Alternative: insert the code locally (refused: only the server knows whether another active mapping
     still covers it and where it sorts).

## Data
No table, no column, no reference code, no migration. `job_runs.counters` (JSONB, derived) gains the key
`rules_fingerprint` on `rescore` rows; `schema.md` describes `counters` as free-form counters, so no paragraph changes.

## Services
- `services/matching.py`:
  - `rules_fingerprint(session) -> str` (decision 1);
  - `rules_dirty(session) -> bool` (decision 1);
  - `ScoreReport.rules_fingerprint`, included in `as_dict` when set; `add` leaves it alone;
  - `rescore_all`: `total.rules_fingerprint = rules_fingerprint(s)` just before `RuleSet.load(s)`;
  - `claim_rescore`: `rules_dirty(s)` in place of `rules_changed_since(s, last_rescore_start(s))`;
  - `rescore_if_dirty`: the follow-up test by fingerprint.
  No audit change (a rescore is system work recorded in `job_runs`, as today).
- `services/matching_rules.py` `_counsel_codes_stmt`: `list_search.parse` (decision 2); raises `ListSearchError`.

## API
| Method and path | Function (`Permission`) | Change |
|---|---|---|
| `GET /admin/counsel-codes` | `admin.counsel_codes` | `q` checked: trimmed, 2-100 characters, else 400 `bad_q`; a blank `q` is no search (`total_all` null). Response unchanged. Visibility unchanged (the caller's office subtree plus generic codes; all for the super admin). |

No other endpoint changes. Searching is not audited (design list-search).

## Jobs
None new. The `rescore-dirty` beat (every 15 minutes, `jobs/celery_app.py:81`) and the save-time dispatch use the new
dirty test through `rescore_if_dirty`.

## Tests
pytest (`tests/db/test_rescore_on_save.py` unless named):
- `test_a_save_committed_after_the_run_loaded_its_rules_gets_a_follow_up`: make the rules dirty and commit; open
  session A and create a keyword (flush, no commit) so its timestamps precede the claim; run
  `rescore_if_dirty(world.Session, dispatch=...)` with `matching.RuleSet.load` wrapped to commit A right after the
  original load. The dispatch is called exactly once; the next `rescore_if_dirty` runs (not None); the one after
  returns None. (Fails on today's code: no dispatch and the next claim says clean.)
- `test_each_run_records_the_rules_fingerprint`: a finished run's `counters["rules_fingerprint"]` equals
  `rules_fingerprint` read after it; any create, update, deactivate of a code, keyword, pattern, watchlist row, office
  or scoring setting changes the fingerprint.
- `test_a_run_without_a_fingerprint_falls_back_to_timestamps`: a succeeded `rescore` row with empty counters and no
  later change → `claim_rescore` returns None; a later change → a claim.
- The existing `test_one_rescore_at_a_time`, `test_a_change_during_a_run_dispatches_one_follow_up`,
  `tests/db/test_matching.py::test_rescore_if_dirty_follows_rule_edits` and
  `tests/db/test_scoring_settings.py::test_rescore_if_dirty_after_settings_change` pass unchanged.
- `tests/db/test_api_matching.py::test_counsel_codes_bad_q_is_400`: `q="a"` and `q="x"*101` → 400 with
  `detail.code == "bad_q"`; `q="   "` → 200, the full list, `total_all` null; the existing
  `test_counsel_codes_total_all_with_q` passes.

vitest (`frontend/src/components/admin/mapping.test.tsx`):
- "deactivating a code from the row menu reloads Recommended From Cause Lists": after the confirmed Deactivate,
  `GET /admin/counsel-codes/unmapped/page` is called once more (without a cursor).
- "mapping a code drops it from the panel without a request" (today's behaviour) still holds, and Reactivate and an
  office move make no extra unmapped-page request.

## Verification
1. `ruff check` clean; `pytest -q` green; frontend `tsc`, `eslint`, vitest green; `gen:api` shows only the 400 entry
   of `GET /admin/counsel-codes`.
2. No migration: `alembic heads` unchanged.
3. On the dev stack after deploy (no court call): the first `rescore` run after the deploy writes
   `counters.rules_fingerprint`; `aslms rescore` then a save on Department Mapping starts exactly one run.
4. Owner's browser check at http://localhost:3000, Department Mapping, Counsel Codes: deactivate a mapped code that
   appears in cause lists; it shows in Recommended From Cause Lists at once, without a reload.

## Open questions
None.
