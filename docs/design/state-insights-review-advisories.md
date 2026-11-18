# Design: State Insights, review advisories (dirty test, rebuild maps, department filter, phrases, case-type lines, group writes, year filed)

```
slug: state-insights-review-advisories
status: approved
author: architect
date: 2026-11-18
approved_by: owner on 2026-11-18
```

## Context
Backlog row 267 (integrator, 18 Nov 2026). These are the seven reviewer advisories of row 258 `state-insights`
(design `docs/design/state-insights.md`, approved 14 Nov 2026; merged 18 Nov 2026 as `5f59cf0`, report
`docs/reports/2026-11-18-state-insights.md`). They were left open at the merge, none blocking. The row is built
**before row 259** `state-insights-portal`, so the portal is built on the corrected filters and write answers.

Migration 0039 is not yet applied to the dev database (it is at 0038 on 18 Nov 2026). Row 258's deploy is still the
owner's step. If rows 258 and 267 are deployed together, the reader-version change of decision 4 costs nothing extra:
the first build reads every case anyway.

**The seven points of the row, as found in the code.**
1. **The dirty test misses an open transaction.** `insights_facts.DIRTY_SQL` compares `cases.updated_at`,
   `orders.updated_at`, `order_sections.created_at` and `causelist_entries.created_at` with `insight_case_facts.built_at`.
   All of these are `now()`, which is the start of the writing transaction (`set_updated_at()` and the `now()` server
   defaults). `build` stores `built_at = now()`, the start of the build transaction.

   A writer W that starts at t0, has not committed when the build B (started at t1 > t0) reads, and commits after B
   leaves `updated_at = t0 < t1 = built_at`. That change is never dirty. Deviation 8 of the state-insights note
   ("a change committed while a batch is read is never older than its row") is therefore wrong.
2. **The rebuild keeps stale maps.** `rebuild` reads `attribution_fingerprint` and `load_maps` once, before its first
   batch. Each batch is its own transaction under `REFRESH_LOCK`, so a 10-minute `refresh` can run between two batches.
   - If a mapping changed, that refresh records the new fingerprint and re-derives every row.
   - The rebuild's later batches then write rows with the old maps.
   - `_last_fingerprint` orders by `started_at`, so the refresh's newer fingerprint stays "last", and nothing re-derives
     those rows until the next 04:45 rebuild.
3. **The department filter crosses departments.** `insights_filters.parse` accepts any department code in `dept`, and
   `band` with it, whatever the scope. In a department scope, `dept=<other>&band=likely` counts the scope's cases by
   another department's open recommendations. Decision 20 says other departments' recommendations stay theirs.
4. **Some phrases are listed but can never be mapped.** `insights_rules.normalise_phrase` keeps every character that
   `clean` leaves, but `PHRASE_RE` and `ck_office_title_names_phrase` accept only `A-Z 0-9 space ( ) & . , / -`, with a
   letter or digit first.
   - A phrase with an apostrophe, a quotation mark, `[`, `]`, `:` inside it, or any non-ASCII letter or dash is still
     kept, counted and listed on `GET /admin/title-names/unmapped`.
   - `POST /admin/title-names` refuses that same phrase with 400 `bad_phrase`.
5. **On a fresh database every case type reads `other`.** Case-type lines are written only by migration 0039 and
   `insights_groups.seed`, and both need `case_types` rows to exist. On a fresh database the court masters sync
   creates those rows after `init`, so every type reads `other` until `init` is run again. The facts depend on it too:
   `CASES_SQL` reads the `contempt` kind to decide whether to read the original writ (decision 10).
6. **Group writes answer with zero counts.**
   - The router's `_group_out` answers `POST` and `PATCH /admin/insights/groups` with `members`, `cases` and `pending`
     hard-coded to 0.
   - `PUT /admin/insights/case-types` answers `full_name: null, cases: 0, pending: 0`.
   - `PUT /admin/insights/categories` leaves `cases` and `pending` at their schema default of 0.
   - `sort_order` has no bound. A value past the `integer` range fails in PostgreSQL and answers 500.
7. **An older year matches nothing.** `filed` accepts any year from 1950 to this year (decision 24). The expression
   `Expr.filed` buckets every year older than the last 8 as `earlier`, and the condition compares the bucket, so
   `filed=2012` matches no case.

**What this row does not cover.** No screen (row 259). No change to the bands, the scope rules, the readers' rules
other than the phrase normal form, or the export fields. No migration.

## Decisions

1. **The dirty test reads a watermark, not the build's own start.**
   - `built_at` becomes the build's **watermark**: the time before which every committed change is reflected in the
     row. It is taken as the first statement of `build`, before any case data is read:
     `greatest(now() − INSIGHTS_DIRTY_LOOKBACK_MINUTES, least(now(), oldest open transaction − 1 µs))`.
   - The **oldest open transaction** is `min(xact_start)` over `pg_stat_activity` rows that are in this database, are
     `client backend`, are not the build's own backend, and have a `xact_start`. The read runs after
     `pg_stat_clear_snapshot()`, so it is current and not the transaction's cached statistics.
   - Taking 1 µs off keeps the comparison strict (`>`). A writer that is open when the watermark is read has
     `updated_at = its xact_start > watermark`, so it is dirty. A change made inside the build's own transaction has
     `updated_at = now() ≥ watermark`; it is seen by the build and stays clean when no other transaction is open.
   - **Why this is complete.** Every writer to `cases`, `orders`, `order_sections` and `causelist_entries` that is not
     seen by the build is one of two kinds:
     - open when the watermark is read: its start is at or after the watermark;
     - started later: its start is after the build's `now()`.

     Either way its `now()` stamp is newer than `built_at`. The writers are the `api`, `worker`, `worker2` and
     `scheduler` services and the CLI. All of them connect as `aslms_app`, and a role sees `xact_start` for its own
     sessions without any grant. Sessions of other roles (`migrate`, `init` and backups as the owner) show a NULL
     `xact_start` and are ignored. `migrate` and `init` run with the app stopped, and the 04:45 rebuild repairs what
     they change.
   - **The lookback** `INSIGHTS_DIRTY_LOOKBACK_MINUTES` (default 60, 0 to 1,440; not secret) caps how far the watermark
     can fall behind. Without it, a session left open would hold the watermark back and keep re-dirtying every case
     changed since then, run after run. The server's `idle_in_transaction_session_timeout` is 15 minutes, so 60 covers
     every normal transaction.
   - **The guarantee, in words:** a change is in the readings within one refresh run (10 minutes) of its commit, when
     its transaction lasted under the lookback; otherwise by the next 04:45 rebuild. Setting 0 restores the old
     behaviour (the build's own start).
   - The **dirty rules keep `>`.** The trigger columns are unchanged. Decision 5 adds one more trigger.
   - **Cost:** a case changed while another transaction was open is built once more on the next run. That is bounded
     by the lookback and by `INSIGHTS_REFRESH_BATCH`.
   - Deviation 8 of the state-insights note is replaced by this decision. The decisions log says so, and the
     state-insights note gets a one-line pointer under its Deviation 8 (appended, not rewritten).

   *Alternatives:* a fixed margin (`updated_at > built_at − X`) was rejected: it rebuilds every recent change again
   whether or not anything was open, and still misses a transaction longer than X. Snapshot visibility of `xmin`
   (`pg_visible_in_snapshot`) was rejected: 32-bit `xmin` against `xid8`, freezing and wraparound make it fragile.
   Granting `pg_read_all_stats` to `aslms_app` was rejected: it widens a role for no gain, since the app's own writers
   are all `aslms_app`.

2. **The rebuild reloads its maps per batch and compares the fingerprint at the end.**
   - **Per batch.** Each batch transaction, after it takes `REFRESH_LOCK`, reads `attribution_fingerprint`. When that
     differs from the fingerprint of the maps in hand, it reloads `load_maps`. The fingerprint is always read before
     the maps, the order `refresh` already uses: if a change lands between the two reads, the next run re-derives once
     more rather than missing it. So no batch is written with maps older than a fingerprint some refresh has already
     recorded. A refresh cannot run during a batch, because it only tries the lock.
   - **At the end.** One last transaction, under the lock, reads the current fingerprint F_end.
     - If F_end differs from the first batch's fingerprint, it runs `rederive_departments` with maps loaded after
       F_end, adds the count to `rederived`, and records F_end.
     - Otherwise it records the first fingerprint.

     So the fingerprint the rebuild records is true of every row it wrote.
   - `_last_fingerprint` stays as it is. With both steps, a stale "last" fingerprint can only cause one extra
     re-derivation, never a missed one. A failed rebuild records nothing (only `succeeded` runs count), and its batches
     were written with maps no older than any recorded fingerprint.

   *Alternative:* per-batch reload only, recording the first fingerprint, is also correct. It was rejected because it
   leaves correctness to the next refresh's comparison, while the end step makes the rebuild's own record true. Both
   steps are cheap: the three tables are small, and the re-derivation writes changed rows only.

3. **`dept` and `band` are State scope only.** `parse` refuses `dept` with 400 `bad_filter`, `param: "dept"` ("dept is
   for the State's Insights") when `scope.is_state` is false. That includes a State-wide holder who opens one
   department's view: that view shows By Unit, not By Department (decision 19).
   - `band` without `dept` stays `bad_filter` on `band`. `band` with `dept` in a department scope is refused on `dept`.
   - The rule mirrors `unit`, which is refused outside a department scope.
   - It applies to `GET /insights`, `GET /insights/cases` and `POST /insights/export` alike, because they share `parse`.

   *Alternative:* accepting `dept` equal to the scope's own department as a no-op was rejected: it adds a second way to
   say nothing, and the department view has no By Department chart to set it.

4. **The phrase normal form gives only characters the mapping accepts. `READER_VERSION` becomes "2".**
   `normalise_phrase` applies these steps in order, after `clean` (upper case, `&` as ` AND `, page marks dropped):
   1. Unicode NFKD, with combining marks dropped (`É` → `E`).
   2. Typographic dashes (U+2010 to U+2015, U+2212) become `-`.
   3. Apostrophes and quotation marks (`'`, `` ` ``, `´`, U+2018 to U+201F, `"`) are removed with no space, so
      `P.W.D.'S` → `P.W.D.S`.
   4. `[` and `{` become `(`; `]` and `}` become `)`.
   5. Every other character outside `A-Z 0-9 space ( ) . , / -` becomes a space. That covers `:`, `;` and any remaining
      non-ASCII character.
   6. The existing steps follow: section marks, collapsed whitespace, edge punctuation, a leading THE. Leading
      characters are also stripped until the first letter or digit.

   - `_keep` also requires `valid_phrase`, so **every phrase stored in `title_phrases`, and so every phrase on the
     unmapped list, passes `ck_office_title_names_phrase`**.
   - `POST /admin/title-names` already normalises through the same function (`matching_rules._title_phrase`). A person
     who types the printed form maps exactly the phrase the reader lists.
   - On a phrase that already passes `PHRASE_RE`, the normal form changes nothing. The stored `office_title_names` rows
     passed that check, so they keep matching. The normal form is also idempotent.
   - Raising `READER_VERSION` to "2" makes every fact row dirty (decision 12). The 10-minute job re-reads them at 5,000
     a run, about 17 runs for 83,000 cases, or `aslms insights refresh --all` does it at once. No court call, no model.

   *Alternative:* widening `ck_office_title_names_phrase` (a migration) to accept quotes, colons and non-ASCII was
   rejected. Two phrases differing only by a curly or straight apostrophe would become two mappings, and the check's
   purpose is one spelling per printed name.

5. **The refresh job places the seed case-type lines a case type lacks, and a line change re-reads its cases.**
   - **The placement.** A new `insights_groups.place_seed_case_types(session) -> int` covers every court with
     `ref_code = 'GHC'`. For every `case_types` row of those courts whose `case_type_code` is in `SEED_CASE_TYPES` and
     which has no `insight_case_type_groups` row, it inserts the seed line. It never changes an existing line: a
     Super Administrator's choice, even Other, is always a row (`set_case_types`), so "no row" means nobody has chosen.
     `seed()` calls it for its case-type part, so there is one code path.
   - **When it runs.**
     - `refresh` calls it first, before the fingerprint and the dirty selection.
     - `rebuild` calls it in a short first transaction under the lock.
     - The count goes to a new counter `case_type_lines`.
     - `refresh --dry-run` counts what it would place and writes nothing.
   - **A line change re-reads its cases.** `DIRTY_SQL` gains `OR EXISTS (SELECT 1 FROM insight_case_type_groups ctg
     WHERE ctg.case_type_id = c.case_type_id AND ctg.updated_at > f.built_at)`. Then a line just placed, or a Super
     Administrator's move, re-reads the cases of that type. That matters for the `contempt` input of the original-writ
     reading (decision 10). Moving a large type dirties its cases, which are re-read at `INSIGHTS_REFRESH_BATCH` a run.
     The counts themselves change at once, because the kind is joined at query time.
   - **No audit row for a placement.** It is reference data, the same lines the migration and the seed write, under
     the 0016 precedent and the seed's own rule. The Super Administrator's moves stay audited
     (`insights.case_type_grouped`).
   - **`aslms insights groups check`** stays read-only. It adds `case_types_seed_would_place` and lists those types,
     so an operator sees what the next run will place.

   *Alternative:* placing lines only from `groups check --apply` was rejected: it needs a person to remember a step
   after every masters sync, the very gap the advisory names.

6. **Group writes answer with the same line as the list, and `sort_order` is 0 to 10,000.**
   - **Groups.** A new `insights_groups.group_line(session, row)` returns one group's GET item (`id`, the summary,
     `members`, `cases`, `pending`), counted by the helpers `list_groups` uses. `list_groups` builds its items through
     the same counting, so the numbers are identical. The router's `_group_out` uses it for `POST` and `PATCH`.
   - **Categories and case types.**
     - `set_categories` returns, for each changed code, the line `list_categories` would show (`code`, `label`,
       `group`, `cases`, `pending`).
     - `set_case_types` returns the `list_case_types` line (`id`, `code`, `name`, `full_name`, `group`, `cases`,
       `pending`).
     - The router returns those lines as they are, with no hard-coded fields.
   - **The bound.** `sort_order` is a whole number from 0 to `SORT_ORDER_MAX = 10000`. The service refuses anything
     else with `GroupsError("bad_sort_order", …)`, which answers 400. That covers values past the integer range: the
     answer is 400, never 500. The automatic order of `create_group` is `min(max + 10, 10000)`. The seeded orders run
     10 to 200.

   *Alternatives:* Pydantic bounds were rejected, because they answer 422 rather than the 400 every other Insights
   refusal uses. A CHECK constraint (migration 0040) was rejected: it is not needed, because the service is the only
   writer and the column's own type is the last guard. No migration for a range check.

7. **`filed` compares the year itself.** `Expr` gains `year`: the registration year, or the filing year when there is
   none.
   - The `filed` condition becomes:
     - a year: `year = <year>`;
     - `earlier`: the bucket (`year` at or before this year − 8);
     - `unknown`: `year IS NULL`.
   - The accepted values stay those of decision 24: 1950 to this year, plus `earlier` and `unknown` (deviation 9 of the
     state-insights note). The message becomes "filed is a year from 1950 to <this year>, earlier or unknown".
   - The chip reads "Filed: 2012". The chart keeps its 8 years and Earlier. For row 259: when `filed` is a year older
     than the chart, no bar is highlighted and the chip still removes the filter.

   *Alternative:* accepting only the 8 chart years was rejected. A saved or shared address with `filed=2018` would
   start answering 400 when the year turns, and decision 24's table already promises any year.

No decision deviates from the plan. Decision 1 corrects the state-insights note's Deviation 8, and decision 7 makes the
code do what that note's decision 24 already says.

## Data
No new table, no new column, no migration. Two paragraphs of `docs/schema/schema.md` change wording only.

- **`insight_case_facts`**, the `built_at` column. In place of "built_at (timestamptz NOT NULL)":

  > built_at (timestamptz NOT NULL; the build's watermark: every change committed before it is reflected in the row.
  > It is the build transaction's start, or 1 µs before the start of the oldest open transaction of the application
  > role at that moment when that is earlier, never more than `INSIGHTS_DIRTY_LOOKBACK_MINUTES` earlier; the dirty
  > test compares the change times of the case, its orders, their readings, its cause-list entries and its case
  > type's line with it)

- **`insight_case_type_groups`**. In place of "The migration and the seed map the 57 case types in use by court and
  `case_type_code`; the court master sync never writes this table.":

  > The migration, the seed and the `insights-refresh` and `insights-rebuild` jobs place the seed line of each of the
  > 57 seeded case types (by court and `case_type_code`) that has none; a placed line is reference data (no audit
  > row), and an existing line is never changed by them. The court master sync never writes this table. A line's
  > `updated_at` makes its cases' readings dirty.

No `ref_*` codes. Error code `bad_sort_order` (400) is new, and `bad_filter` gains one more case (`dept` outside the
State scope). Both are added to the error list of the API section of `docs/design/state-insights.md` by the scribe.

## Services

- **`services/insights_facts.py`**
  - `watermark(session) -> datetime`: decision 1. One statement after `pg_stat_clear_snapshot()`, reading
    `INSIGHTS_DIRTY_LOOKBACK_MINUTES`. It is a function, so tests can replace it.
  - `build(session, case_ids, *, maps=None, now=None)`:
    - when `now` is None, `built_at = watermark(session)` is taken first, before `gather`;
    - `today` and a new category's `first_seen_at` stay the transaction's `now()`;
    - a given `now` (tests) is used for all three, as today.
  - `DIRTY_SQL`: the case-type line clause of decision 5. The comparisons stay `>`.
  - `refresh`: calls `insights_groups.place_seed_case_types` first; counter `case_type_lines`; the dry run counts with
    `insights_groups.count_seed_case_types_missing`.
  - `rebuild`:
    - a first transaction under the lock places the seed lines;
    - each batch reads the fingerprint under the lock and reloads the maps when it changed;
    - the end transaction under the lock compares with the first fingerprint and re-derives when it differs
      (decision 2);
    - `unmapped_phrases` is counted with the maps of that end step.
  - `COUNTERS` gains `case_type_lines`. `_last_run` and the data-health block show it, which is additive.
- **`services/insights_rules.py`**: `normalise_phrase` as decision 4; `_keep` adds `valid_phrase`;
  `READER_VERSION = "2"`. A module constant `PHRASE_ALLOWED` documents the character set shared by `PHRASE_RE` and the
  check constraint.
- **`services/insights_filters.py`**:
  - `parse` refuses `dept` outside the State scope (decision 3), and its `filed` message changes (decision 7);
  - `Expr` gains `year`;
  - `conditions["filed"]` compares the year, the bucket or NULL (decision 7);
  - the chip for a year reads "Filed: <year>".
- **`services/insights_groups.py`**:
  - `place_seed_case_types` and `count_seed_case_types_missing` (decision 5), with `seed()` calling the first;
  - `group_line`;
  - `SORT_ORDER_MAX` and `_sort_order(value)`, used by `create_group` and `update_group`;
  - `set_categories` and `set_case_types` return list lines with real counts (decision 6).

  The audit rows are unchanged: `insights.group_created`, `insights.group_updated`, `insights.category_grouped` and
  `insights.case_type_grouped`. The `before` and `after` values stay the group summary and code pairs; the counts are
  not audited.
- **`cli/insights.py`**: `groups check` prints `case_types_seed_would_place` and lists them (decision 5). `refresh
  --dry-run` shows `case_type_lines`.
- **`core/config.py`**: `insights_dirty_lookback_minutes: int = Field(60, ge=0, le=1440)`. It is added to the example
  environment file with a comment and is not secret.

Nothing here reads a note, a draft, a custody remark, a document or a document description, or calls NAPIX,
SourceTrace or a model. The static scan `test_insights_static.py` still covers every Insights module.

## API
No new endpoint and no new field. The changes to existing endpoints:

| Endpoint | Function required | Change |
|---|---|---|
| `GET /insights`, `GET /insights/cases`, `POST /insights/export` | `insights.state` or `insights.department` (scope rules of decisions 18 and 19) | 400 `bad_filter` with `param: "dept"` when `dept` is given outside the State scope (decision 3). `filed=<year>` counts the cases of that year (decision 7). Visibility is unchanged and still ANDed in SQL. |
| `POST /admin/insights/groups`, `PATCH /admin/insights/groups/{group_id}` | `admin.insights_groups` (reserved, Super Administrator) | The answer carries the real `members`, `cases` and `pending` (decision 6). 400 `bad_sort_order` outside 0 to 10,000. |
| `PUT /admin/insights/categories` | `admin.insights_groups` | Each changed line carries its real `cases` and `pending`. |
| `PUT /admin/insights/case-types` | `admin.insights_groups` | Each changed line carries its `full_name`, `cases` and `pending`. |
| `GET /admin/title-names/unmapped`, `POST /admin/title-names` | `admin.keywords` (office subtree; super admin everywhere) | No shape change. Every listed phrase can now be posted as it stands (decision 4). |

The generated `frontend/src/lib/api/openapi.json` and `schema.d.ts` are regenerated if the descriptions change. No
screen changes in this row.

## Jobs
No new job and no new schedule.
- `insights-refresh` (every 10 minutes) places missing seed case-type lines first, then builds with the watermark.
- `insights-rebuild` (04:45 IST) places lines, reloads maps per batch, and re-derives at the end when the fingerprint
  moved.
- The new counter in `job_runs` is `case_type_lines`.
- After deploy, every row is dirty once (`READER_VERSION` 2). Either let the 10-minute job catch up in about three
  hours, or run `docker compose exec api aslms insights refresh --all` once.

## Tests

**Unit** (`backend/tests/unit/test_insights_rules.py`):
- `test_normalise_phrase_folds_refused_characters`: apostrophe, straight and curly quotes, `[`/`]`, `{`/`}`, `:` and
  `;` inside, `É`, an en dash and an em dash, each giving the expected phrase.
- `test_every_kept_phrase_passes_the_title_name_check`: over the existing cause-title fixture corpus plus the cases
  above, every phrase from `department_phrases` matches `PHRASE_RE`.
- `test_normalise_phrase_idempotent_and_unchanged_on_valid`: `normalise_phrase(normalise_phrase(x)) ==
  normalise_phrase(x)`, and a phrase that passes `PHRASE_RE` is returned unchanged.
- `test_reader_version_is_2`.

**Database** (`backend/tests/db/test_insights_facts.py`):
- `test_change_in_transaction_open_during_build_is_dirty`, the regression of advisory 1:
  1. a second connection as `aslms_app` begins and updates a case without committing;
  2. a refresh builds the case and commits;
  3. the second connection commits;
  4. the case is dirty and the next refresh re-reads it.

  The same test is repeated for a new order, an order reading and a cause-list entry.
- `test_watermark_now_without_other_transactions`, `test_watermark_before_oldest_open_transaction` and
  `test_watermark_never_older_than_lookback` (including lookback 0 = the build's own start).
- `test_change_in_build_transaction_not_dirty`: today's same-transaction behaviour is kept. Tests that assert "not
  dirty" run with no other open transaction of the role, or replace `watermark`.
- `test_rebuild_reloads_maps_between_batches`: `batch=1`, with a cause-title mapping saved and committed from the
  `echo` callback after the first batch; every later row names the new department.
- `test_rebuild_rederives_when_fingerprint_moved`:
  1. a mapping is changed and a refresh run between two batches;
  2. after the rebuild, every row equals a fresh `rederive_departments`;
  3. the recorded fingerprint equals the current one;
  4. the next refresh re-derives nothing.
- `test_place_seed_case_types_after_masters_sync`:
  1. the seed runs, then `case_types` rows are inserted (as the masters sync does);
  2. the next refresh places their lines (`case_type_lines` = n);
  3. a line a person set to Other is untouched;
  4. a contempt case of a newly placed type is re-read and takes its original writ;
  5. a second refresh places nothing.
- `test_case_type_line_change_marks_its_cases_dirty`.

**Database** (`backend/tests/db/test_insights.py`, `test_insights_api.py`, `test_insights_groups.py`):
- `test_dept_filter_refused_outside_state_scope`:
  - department scope, with and without `band`: 400 `bad_filter`, `param: "dept"`, on `/insights`, `/insights/cases`
    and `/insights/export`;
  - a State-wide holder's department view: refused;
  - State scope: accepted, with counts unchanged.
- `test_filed_year_older_than_chart_matches`:
  - `filed=<this year − 10>` counts the case registered that year, and a case with only a filing date in that year;
  - `earlier` still counts the whole bucket, and `unknown` counts no-date cases;
  - 1949 and next year answer 400;
  - the chip reads "Filed: <year>".
- `test_group_writes_answer_real_counts`: the `POST` and `PATCH` group answers equal that group's item in the following
  `GET`, and the `PUT` category and case-type lines equal the same lines in the following `GET` (non-zero cases in the
  fixture).
- `test_sort_order_bounds`: −1, 10,001 and 2^40 answer 400 `bad_sort_order` on create and patch; 0 and 10,000 are
  accepted; the automatic order stops at 10,000.
- `test_listed_phrase_can_be_mapped`:
  1. a cause title with `P.W.D.'S DEPARTMENT` and one with a curly quote both list one phrase;
  2. `POST /admin/title-names` with that listed phrase succeeds;
  3. after the refresh the case names the department and the phrase leaves the unmapped list.

**CLI** (`backend/tests/db/test_insights_facts.py` or the CLI test module): `test_groups_check_reports_seedable_types`
and `test_refresh_dry_run_counts_case_type_lines` (writes nothing).

Every existing Insights test stays green, including `test_dirty_rules_each_trigger` and
`test_reader_version_change_marks_all_dirty`. `ruff check .` is clean and `pytest -q` is green.

## Verification
The integrator, after the merge, with 0039 applied (row 258's deploy) and the app services recreated:
1. `docker compose exec api aslms insights refresh --all`, then `aslms insights status`: `facts_waiting` is 0 and every
   row has `reader_version` 2.
2. Read-only SQL on dev: `SELECT count(*) FROM insight_case_facts f CROSS JOIN LATERAL unnest(f.title_phrases) p WHERE
   p !~ '^[A-Z0-9][A-Z0-9 ()&.,/-]{2,199}$'` gives **0**. Record the number of distinct unmapped phrases before and
   after in the report.
3. `aslms insights groups check`: `case_types_seed_would_place` is **0**. Record `case_types_without_line` (types
   outside the seed list, read as Other).
4. **The scope refusal**, as a Department Head with `insights.department`: `GET /insights?scope=department&dept=<another
   department>` answers 400 `bad_filter` with `param` `dept`. As the super admin, `GET /insights?scope=state&dept=<code>
   &band=likely` answers 200.
5. **The year filter.** `GET /insights?scope=state&filed=<this year − 10>` gives a non-zero `headline.cases`. It
   equals `total` of `GET /insights/cases` with the same parameters, and every listed case was registered in that year
   (or filed in it, when it has no registration date).
6. **The sort order.** `PATCH /admin/insights/groups/{id}` with `sort_order` 99999999999 answers 400 `bad_sort_order`.
   A rename answers with the same `cases` as `GET /admin/insights/groups`.
7. **The open-transaction case**, on a scratch database by the test suite only (the dev stack is never held open by
   hand).

## Open questions
None.
