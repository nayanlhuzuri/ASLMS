# Design: Cause-title signal, review advisories (no double counting, the fact row as the engine's only source, a durable rescore marker, the shown phrase, the runbook order)

```
slug: cause-title-signal-review-advisories
status: approved
author: architect
date: 2026-11-21
approved_by: owner on 2026-11-21
```

## Context
Backlog row 273 (integrator, 21 Nov 2026). These are the five reviewer advisories of row 260 `cause-title-signal`
(round 3 of `docs/design/state-insights.md`, section K, decisions 36 to 40, and the developer's deviations 34 to 43).
The owner ruled on 21 Nov 2026: **fix all five before row 260 is deployed**. The double counting of point 1 must stop,
so the same respondent party row never counts twice for one department. Rows 260 and 273 then deploy together in one
night window, with the dry run of runbook section 27 shown to the owner before the services return.

Where things stand. Row 260 is merged on `main` (a8da90e) and is **not deployed**: migration 0040 is not applied to the
dev database, so no score row with engine version `3.x` has been written outside tests. The engine
(`services/matching.py`) reads `insight_case_facts.named_title_department_ids` and `title_phrases`. It loads the
cause-title maps (`insights_facts.load_maps`) into `RuleSet.title_maps` to check that a stored phrase still names the
department and to choose the phrase shown. The Insights jobs keep the in-memory list `named_changed_ids` and rescore it
after a successful run (`insights_facts.rescore_changed`).

The five points and what this note does about each:
1. **Double counting** (`_named_hits`, `_gather_title`). With the source `party`, the signal counts the same respondent
   name that a keyword or name pattern of the same department already scores. Example: "Commissioner and Secretary,
   Finance Department" matched by a FINANCE name pattern (0.8) and named by the readings (0.6) gives 0.92, so a strong
   recommendation and a strong alert with no new evidence. Decisions 1 to 4 withhold the signal in that case.
2. **Stale maps in a full rescore** (`rescore_all` loads the maps once; `office_title_names` is outside
   `rules_fingerprint`). Decisions 5 to 7 remove the maps from the engine, so a full rescore can never use maps older
   than the fact rows.
3. **The rescore list lives in memory.** If a rebuild fails after some batches commit, or the worker stops before
   `rescore_changed`, those fact rows are never rescored. Decisions 8 to 12 replace the list with a marker column that
   commits in the same transaction as the fact row.
4. **The shown phrase.** `rederive_departments` rescored a case only when its department ids changed, not when the
   phrase shown changed. Decision 6 stores, for each phrase, which department it names. Any change in that is then a
   change of the row, and the row is marked for rescoring.
5. **Runbook section 27 order.** `docker compose build` now comes before step 1. Decision 14 also adds the new steps.

Not covered here:
- The weight 0.600 itself (row 272, the owner's go-ahead at the deploy).
- The browser checks (row 272).
- Overlap between a keyword and a name pattern of the same department on one name. That is the existing engine (two
  kinds, combined by noisy OR) and was not raised.
- No business rule changes. The engine still never assigns a case. Every claim guard stays (state-insights decision 39).

## Decisions

**A. No double counting (point 1, owner's ruling)**

1. **Respondent evidence already scored for a department.** While the engine scores a case it records, for each
   department D, every respondent name that a keyword or name pattern of D (its own or one of its directorates' or
   units') matched:
   - the current respondent `case_parties` rows matched, each identified by its position in the evidence;
   - **party row 1**, when such a rule matched the respondent summary (`cases.respondent_summary`) or the respondent
     text of a current cause-list entry. Both print the first respondent: NAPIX `res_name` is party 1, and the cause
     list prints the first respondent with "and others".

   The record counts every matching row, not only the first signal that `score_case`'s per-`(kind, rule, where)`
   de-duplication keeps. Petitioner-side matches are never recorded: the readings take department phrases from the
   respondent side only.
   Alternative: the reviewer's example, "skip the party source when a keyword or pattern matched the same party row".
   This decision is that example, made exact for rows the de-duplication hides and for the two texts that print party 1.
2. **When the signal counts.** For a department D in the fact row, take the stored phrases that name D (decision 6),
   in stored order. For each phrase:
   - it **counts** when a current respondent party row not already scored for D gives it
     (`insights_rules.department_phrases` over that row's name, as the engine already runs);
   - it **counts** when no current respondent row gives it (it was read from the cause title of the titled order, or
     from a party row no longer current), but only if no respondent evidence at all is scored for D;
   - otherwise it is **withheld**.

   The first phrase that counts is the one shown, and its source follows round 3's deviation 35: `party` when a current
   respondent row gives it; `cause_title` with the order date when none does and the row names its titled order; else
   `party`. If no phrase of D counts, D gets **no `named_in_title` signal**. Its other signals and its score are
   unchanged. The reviewer's example now scores 0.8 (possible), not 0.92.
   The cause-title-only case is the conservative reading of the owner's rule. The cause title's respondent side lists
   the same respondents as the party rows, but the engine cannot tell which row a phrase printed only in the order
   corresponds to. So when D already has scored respondent evidence, the phrase is treated as the same respondent.
   When D has none, it is new evidence and counts as before.
   Alternative: count a cause-title-only phrase always. Rejected: a different spelling of an already-scored respondent
   would still double count.
3. **Per department, never across departments.** A row scored for department E does not withhold D's signal, even when
   it also names D.
4. **Visible in the dry run, not in Case Claim.** A withheld signal is not written. `score_case` takes an optional
   counter dictionary that `_named_hits` increments, and the dry run reports it as `named_withheld`: the number of
   (case, active department) pairs whose fact row names the department but whose signal was withheld. The runbook
   records it with the other counts (decision 14). The signal's JSON shape is unchanged, and Case Claim shows only
   signals that count.

**B. The fact row as the engine's only source (points 2 and 4)**

5. **The engine reads no cause-title map.** `RuleSet.title_maps`, `RuleSet.title_department` and the call to
   `insights_facts.load_maps` in `RuleSet.load` are removed (this also removes that import cycle). Every department
   and phrase the signal uses comes from the case's fact row. A full rescore therefore cannot apply maps older than the
   rows. The fact rows follow a mapping save through the re-derivation the save already dispatches
   (`dispatch_insights_refresh`), and the re-derivation marks the rows it changed (decision 8).
   Alternatives:
   - Reload the maps per batch when the attribution fingerprint moves, and repeat a batch that ran across a save.
     Rejected: this narrows the window but cannot close it, because the maps and the not-yet-re-derived rows still
     disagree in between.
   - Add `office_title_names` to `rules_fingerprint`. Rejected: round 3's deviation 37 still holds; it would rescore
     every case on each save, before the re-derivation it depends on.

   This **replaces round 3's deviation 36.** A mapping deactivated since the row was derived now keeps its signal until
   the re-derivation runs: seconds after the save when the dispatch reaches a free worker, at most the 10-minute
   `insights-refresh` beat otherwise. That is the same freshness as the Insights page's "Named in the Cause Title"
   counts, so the two always agree. The guard that the department is active and Department-tier stays in the engine.
6. **Each phrase's department stored in the fact row.** New column `title_phrase_department_pos smallint[]`, parallel to
   `title_phrases`. Element *i* is the 1-based position in `named_title_department_ids` of the department that phrase
   *i* names, or 0 when it names none.
   - The builder (`read_case`) and `rederive_departments` compute it with the ids from one new `Maps` method,
     `phrase_positions(phrases) -> (ids, positions)`. The ids keep `phrase_departments`' order and rule: an explicit
     mapping, else the department name core.
   - Both now derive from the **stored** phrases (the clipped list of at most 100 phrases of at most 200 characters).
     So the build and the re-derivation always agree. Today a department named only by a phrase past the hundredth is
     counted at build time and dropped at re-derivation.
   - Positions rather than a second array of office ids: no new array of office ids (DB_STANDARD §2 names the two that
     exist), and no NULL elements.
   - A row whose positions are empty while it holds phrases has not been derived since migration 0041. The engine gives
     it no `named_in_title` signal (decision 13 fills every row before the dry run).
7. **The shown phrase changes the row (point 4).** Two comparisons change:
   - `_named_changed` (build) marks a row when its department ids differ from the stored ones, or, while it names any,
     when its titled order, its phrases or its **positions** differ.
   - `rederive_departments` writes a row when its ids, counsel ids, government codes, bases or positions differ. It
     marks the row when its department ids differ, or when it names any and its positions differ.

   A mapping that changes which phrase names a department therefore reaches Case Claim, even when the set of
   departments stays the same.

**C. A durable rescore marker (point 3)**

8. **`insight_case_facts.named_changed_at`** (timestamptz NULL, partial index). It means: this row's cause-title input
   changed and the engine has not scored the case since.
   - `build` sets it to `clock_timestamp()` on the rows `_named_changed` lists, in the same upsert. Rows not listed keep
     their value (`coalesce(excluded.named_changed_at, insight_case_facts.named_changed_at)`), so an unrelated rebuild
     never clears a pending mark.
   - `rederive_departments` sets it in the same UPDATE on the rows it marks.

   The mark commits or rolls back with the fact row, so a failed rebuild's committed batches and a run stopped before
   any rescore leave their marks behind.
   Alternatives: queue items in `fetch_queue` (rejected: that queue carries the NAPIX lanes, and one row per case would
   flood it); comparing score times with `built_at` (rejected: score rows exist only for a score above 0).
9. **Every engine pass clears the mark it scored.** `CaseEvidence.gather` reads `named_changed_at` with the fact row.
   After `apply_scores`, `_score_one` runs, in the case's savepoint:
   `UPDATE insight_case_facts SET named_changed_at = NULL WHERE case_id = :id AND named_changed_at = :read`.
   - A mark written after the gather has another value and stays. If the refresh's write is still uncommitted, the
     UPDATE waits for it and re-checks against the new value (READ COMMITTED).
   - A full rescore, a cause-list or dossier pass, and the drain all clear the marks of the cases they score.
   - A case whose scoring fails keeps its mark through the savepoint rollback; decision 10 handles it.
10. **The drain, `insights_facts.rescore_marked(session_factory, *, batch=RESCORE_BATCH, stop_at=None)`**, replaces
    `rescore_changed`. It notes its start time, then repeats until no row is left:
    - In a new transaction, take `pg_try_advisory_xact_lock(RESCORE_MARKED_LOCK)`. If another drain holds it, stop:
      that drain does the work.
    - Select up to `batch` rows `(case_id, named_changed_at)` with a mark at or before the start, in `case_id` order,
      after the last id done. Marks newer than the start wait for the next drain, so a drain never chases a busy refresh.
    - Run `matching.score_cases(…, origin=rescore)`.
    - Clear the marks of the cases that failed. The new `ScoreReport.failed_case_ids` (a list, not a counter) names
      them, and the clear uses the same equality test as decision 9. The engine has already recorded each failure in
      `source_failures` (kind `scoring`), as every pass does, so a broken case cannot loop.
    - Commit.

    It returns the engine's `ScoreReport`. The lock is held only per batch. It names no fact-row lock, so the lock
    order stays case row, then fact row (decision 11).
11. **The engine locks the case before it reads the evidence.** `_score_one` takes the case row lock that
    `apply_scores` already takes (`SELECT … FOR UPDATE` on `cases`) before `CaseEvidence.gather`; `apply_scores` keeps
    its own statement, which then takes no new lock. Two engine passes on one case are then serial from the read on:
    the second reads what the first committed. Without this, a full rescore could read a fact row, a refresh plus drain
    could score the new row, and the full rescore's older result could then commit over it.
    - No new lock dependency: the same lock is held in the same transaction, only a few reads earlier.
    - Engine passes still lock in case-id order (`score_cases` sorts).
    - The Insights writes never wait for a case lock.
    - The dry run takes no lock (unchanged).
12. **Who drains.** The marks are the only list, so a drain left undone is resumed by the next one.
    - The `aslms.insights_refresh` task drains after every run, **whether or not the refresh ran**: when
      `refresh_if_free` returns None, the run holding the lock leaves its marks.
    - `rebuild` drains at its end.
    - `aslms insights refresh` (with or without `--all`) drains unless `--no-rescore` is given (decision 13).

    The counter `named_changed` (rows marked by the run) stays. `RunReport.named_changed_ids` goes. The task's and the
    CLI's result field `rescored` is the drain's case count.

**D. The deploy (point 5)**

13. **Every existing row derived once, with nothing rescored before the go-ahead.**
    - `attribution_fingerprint` gains a constant `ATTRIBUTION_VERSION = "2"` in its input. The first refresh after the
      deploy then finds the attribution changed and re-derives every row, filling the positions (no text is read). No
      `READER_VERSION` bump is needed: the builder's text reading is unchanged.
    - `aslms insights refresh --no-rescore` runs the refresh and leaves the marks for later. It prints the number marked
      and the line "a full rescore or the next insights-refresh run scores them". This is for the deploy, where the full
      rescore of the new settings version follows the owner's go-ahead, so the cause-title signal is applied to no case
      before the owner has seen the dry run (state-insights decision 40).
14. **Runbook section 27 rewritten in this order**, all with the court-data switch rules of every `up`:
    - (0) `docker compose build` from the clean worktree of `main`, before anything else (point 5: `migrate` refuses an
      image built from other code, and the dry run needs the new image).
    - (1) The `pre-migrate` backup, then the `migrate` step applying 0040 and 0041.
    - (2) With the scheduler and both workers stopped, `docker compose run --rm --no-deps api aslms insights refresh
      --no-rescore`. Record `rederived`, `named_changed` and the time taken.
    - (3) The dry run. Record `new.medium`, `new_by_kind.medium.named_in_title`, `new_only_with_named`,
      `band_changed_by_named` and `named_withheld` in `docs/design/state-insights.md` and show them to the owner.
    - (4) On the go-ahead, bring the services back. There is no build at this step: `rescore-dirty` rescores every case
      (or run `aslms rescore --all` at once), and the 10-minute refresh drains what the rescore left marked.
    - (5) Checks: no engine-written ownership; no score row below engine version 3; `named_rescore_waiting` back to 0.

    Roll-back gains: downgrade 0041 before 0040.
15. **Engine version stays `3`.** No `3.x` score row exists outside tests (0040 is not applied), and the deploy rescores
    every case. A fourth version would only make section 27's step-5 check read `4.%` for no gain.

## Data
**Migration 0041** `0041_cause_title_signal_marker.py` (hand-written, revises 0040; takes the next free number if
another migration lands first). Applied migrations are never edited. `docs/schema/schema.md` is extended before the
migration is written.

- Upgrade:
  - `ALTER TABLE insight_case_facts ADD COLUMN title_phrase_department_pos smallint[] NOT NULL DEFAULT '{}'`. This is
    metadata only in PostgreSQL 16; no table rewrite.
  - `ADD COLUMN named_changed_at timestamptz NULL`.
  - The check `ck_insight_case_facts_phrase_pos`.
  - The partial index `ix_insight_case_facts_named_changed_at`.
- No data step: the positions are filled by the first refresh (decision 13), because the attribution rules are code.
- No audit row (a schema change to a derived table, as 0039).
- Downgrade drops the index, the check and both columns.

**`schema.md`, the `insight_case_facts` paragraph**, gains after `title_phrases`:

> title_phrase_department_pos (smallint[] NOT NULL default `{}`; parallel to `title_phrases`: element *i* is the
> 1-based position in `named_title_department_ids` of the department phrase *i* names (an explicit active mapping,
> else the department name core), 0 when it names none; empty only on a row not derived since migration 0041; written
> by the builder and the re-derivation from the stored phrases, so `named_title_department_ids` is exactly the
> departments the stored phrases name, in order of first phrase); named_changed_at (timestamptz NULL; set, by
> `clock_timestamp()` in the same statement as the row, when the departments named or, while it names any, the titled
> order, the phrases or the positions change; cleared by the matching engine when it scores the case with the row
> carrying that value, and by the drain `insights_facts.rescore_marked` for a case whose scoring failed (recorded in
> `source_failures`)).

> Checks, added: `ck_insight_case_facts_phrase_pos` (`cardinality(title_phrase_department_pos) = 0 OR
> (cardinality(title_phrase_department_pos) = cardinality(title_phrases) AND array_position(title_phrase_department_pos,
> NULL) IS NULL AND 0 <= ALL (title_phrase_department_pos) AND cardinality(named_title_department_ids) >= ALL
> (title_phrase_department_pos))`). Index, added: partial `ix_insight_case_facts_named_changed_at` (named_changed_at)
> WHERE named_changed_at IS NOT NULL.

The table class (derived), its keys (case_id PK → cases RESTRICT), FK behaviour and audit columns (created_at,
updated_at) are unchanged. No FK is involved: positions are not ids.

**`schema.md`, the `case_office_scores` row**: "a `named_in_title` signal … is read from
`insight_case_facts.named_title_department_ids`" becomes "… is read from `insight_case_facts` (the departments named
and each phrase's position, never a map), one per department, and is withheld when every phrase naming the department
comes from respondent evidence a keyword or name pattern of that department already scored (design
`cause-title-signal-review-advisories`, decisions 1 and 2)". The engine version text is unchanged.

No reference codes are added. No `.env` key or setting is added.

## Services
- **`services/matching.py`**
  - `CaseEvidence` gains:
    - `respondent_rows: list[tuple[int, frozenset[str]]]`: the position in `names` of each current respondent party
      row, and its department phrases;
    - `respondent_name_idx: set[int]`: the `names` positions of respondent-side texts (respondent rows, the cause-list
      entries' respondent text, `respondent_summary`);
    - `first_respondent_idx: int | None`: the position of party row 1;
    - `title_positions: list[int]`;
    - `fact_marker: datetime | None`.

    `respondent_phrases` (the union) stays.
  - `_gather_title` reads `title_phrase_department_pos` and `named_changed_at` with the fact row. It reads the marker
    even when the row names no department.
  - `score_case(rules, evidence, stats=None)`: the name loop records, for every keyword or name-pattern match of
    department D on a respondent-side position, the scored respondent rows of D (decision 1). This happens outside the
    `seen` de-duplication. `_named_hits(rules, evidence, seen, scored_rows, stats)` applies decision 2.
  - `RuleSet` loses `title_maps` and `title_department`, and `load` no longer imports `insights_facts`.
  - `_score_one` takes the case row lock before `gather` and clears the marker after `apply_scores` (decisions 9 and 11).
  - `ScoreReport.failed_case_ids` (not in `as_dict`) is filled by `score_cases`.
  - `DryRunReport.named_withheld` is filled through `score_case`'s `stats`. The dry run takes no lock and clears no
    marker.
  - No audit row: engine writes keep the system actor (`matching`) and are recorded by events and score rows, as
    before.
- **`services/insights_facts.py`**
  - `Maps.phrase_positions`.
  - `read_case` derives the ids and positions from the stored (clipped) phrases.
  - `_named_changed` compares the positions too.
  - `build` writes `named_changed_at` (decision 8).
  - `rederive_departments` compares and writes the positions and marks rows (decisions 7 and 8). Its `named_changed`
    parameter becomes a counter of the rows marked.
  - `ATTRIBUTION_VERSION` goes into `attribution_fingerprint`.
  - `rescore_marked` replaces `rescore_changed`, with `RESCORE_MARKED_LOCK = 0x41534C4D53_0273`.
  - `refresh` and `rebuild` lose `named_changed_ids`. `rebuild` calls `rescore_marked` at its end.
  - `status()` adds `named_rescore_waiting`: rows with a mark, live cases only.
  - Still no audit row, no NAPIX, SourceTrace or model call, no note or internal document read.
- **`jobs/celery_app.py`**: the `aslms.insights_refresh` task runs `rescore_marked` after `refresh_if_free`, whatever
  that returned (decision 12). `aslms.insights_rebuild` is unchanged (the drain is inside `rebuild`).
- **`cli/insights.py`**: `refresh` gains `--no-rescore`, with and without `--all` (decision 13). Its dry run is
  unchanged; `status` prints the new count.
- **`cli/matching.py`**: the dry-run output includes `named_withheld`.
- **Docs**:
  - `docs/operations.md`: section 27 as decision 14; section 26 names the marker, the drain and `--no-rescore`.
  - `docs/schema/schema.md`: as in Data.
  - `docs/design/state-insights.md`: one line at round 3's deviations 35 to 37, saying they are superseded by this
    note's decisions 2, 5 and 12.
  - The decisions log entry.
  - CLAUDE.md's deploy item 21: 0040 and 0041, and the step order.

## API
No new or changed endpoint, and no new `Permission`.
- `GET /admin/data-health` (unchanged guard `health_reader`: any of `reports.state`, `admin.napix_refetch`,
  `admin.masters_sync`): the `insights` block (`InsightsStatusOut`) gains one additive field,
  `named_rescore_waiting: int`. Counts only; no case is named, so visibility is unaffected.
- `openapi.json` and the portal's generated `schema.d.ts` are regenerated. No screen changes.
- Case Claim and the case scores read the same signal shape as before. Only signals that count are present
  (decision 4).

## Jobs
- No new schedule or job kind.
- `insights-refresh` (every 10 minutes at minute 4) now also drains the marks, single-flight per batch through
  `RESCORE_MARKED_LOCK`, 500 cases a transaction, origin `rescore`.
- `insights-rebuild` (04:45 IST) drains at its end. If it fails, the next `insights-refresh` drains the marks of its
  committed batches.
- `rescore-dirty` (every 15 minutes) is unchanged in its trigger. Its passes clear the marks of the cases they score.

## Tests
Unit (`tests/unit/test_cause_title_signal.py`, pure `score_case` over built evidence):
- `test_same_respondent_row_matched_by_a_pattern_gives_no_named_signal`: the reviewer's example scores 0.8, medium,
  not 0.92.
- `test_same_row_matched_by_a_keyword_of_a_directorate_withholds_for_its_department`.
- `test_every_matched_row_counts_not_only_the_first_signal`: one keyword matches rows 1 and 3, the phrase is only in
  row 3, so it is withheld.
- `test_another_unscored_respondent_row_naming_the_department_counts_and_is_shown`.
- `test_a_row_scored_for_another_department_does_not_withhold`.
- `test_summary_or_cause_list_respondent_match_scores_party_row_one`.
- `test_petitioner_side_match_never_withholds`.
- `test_cause_title_only_phrase_withheld_when_any_respondent_evidence_is_scored`, and
  `…_counts_with_the_order_date_when_none_is`.
- `test_withheld_signals_are_counted_in_stats`.
- `test_engine_uses_stored_positions_and_no_map`: `RuleSet` has no `title_maps`; a department without a position gets
  no signal; empty positions with phrases give no signal.
- `test_phrase_positions_follow_phrase_departments` (`Maps.phrase_positions`: order, explicit before core, 0 for none).
- `test_read_case_derives_from_the_stored_clipped_phrases`.

Database (`tests/db/test_cause_title_signal.py` and `test_insights_facts.py`):
- `test_double_counting_stops_end_to_end`: pattern plus the same row stays possible, with no strong band, no
  `recommended` event at the strong band and no alert.
- `test_full_rescore_follows_a_title_name_saved_mid_run`: `rescore_all` with `batch=1`, a hook saving a mapping and
  running the refresh and the drain between batches. The final score row carries the new department and phrase.
- `test_engine_locks_the_case_before_reading_evidence`: inside a patched `gather`, a second connection's
  `FOR UPDATE NOWAIT` on the case fails.
- `test_build_marks_changed_rows_only_and_keeps_a_pending_mark`.
- `test_failed_rebuild_leaves_marks_that_the_next_refresh_task_drains`: an error in batch 2; batch 1's rows are drained
  by the task.
- `test_mark_written_after_the_gather_survives_the_clear`: two sessions.
- `test_drain_clears_a_failing_case_and_records_the_failure`: `source_failures` kind `scoring`.
- `test_second_drain_stops_at_the_lock`, and `test_drain_takes_marks_up_to_its_start_only`.
- `test_rederive_marks_a_case_when_only_the_shown_phrase_changes`: same department ids, new positions; Case Claim's
  phrase follows after the drain (point 4).
- `test_first_refresh_after_the_attribution_version_derives_every_row`: the positions fill, the rows are marked, and
  nothing is rescored with `--no-rescore`; the CLI writes no score row.
- `test_dry_run_reports_named_withheld_and_writes_nothing`.
- `test_status_counts_named_rescore_waiting`; `test_data_health_insights_block_has_named_rescore_waiting`.
- `tests/db/test_migration_0041.py`: up and down; the check refuses a length mismatch, a NULL element, a position past
  the ids and a negative one, and accepts empty positions on an old row.
- The existing round-3 tests that call `rescore_changed` or read `named_changed_ids` are moved to the drain and the
  marks. `test_with_a_keyword_still_possible` (keyword on another row, 0.76) keeps its figure.

## Verification
The integrator, on the dev stack, in the night window shared with row 260, following runbook section 27 as rewritten
(decision 14):
1. `docker compose build` from the clean worktree of `main`, then the `pre-migrate` backup and the `migrate` step.
   `alembic current` shows `0041`.
2. Scheduler and both workers stopped: `docker compose run --rm --no-deps api aslms insights refresh --no-rescore`.
   Expected:
   - `rederived` close to the number of fact rows with phrases;
   - `named_changed` equal to the rows naming a department (`SELECT count(*) FROM insight_case_facts WHERE
     cardinality(named_title_department_ids) > 0`);
   - `SELECT count(*) FROM insight_case_facts WHERE cardinality(title_phrases) > 0 AND
     cardinality(title_phrase_department_pos) = 0` is 0;
   - `SELECT count(*) FROM case_office_scores WHERE engine_version LIKE '3.%'` is 0 (nothing scored yet).

   Record the time.
3. `docker compose run --rm --no-deps api aslms rescore --all --dry-run`. Record `new.medium`,
   `new_by_kind.medium.named_in_title`, `new_only_with_named`, `band_changed_by_named` and `named_withheld` in
   `docs/design/state-insights.md`. Show them to the owner and wait for the go-ahead (row 272).
4. On the go-ahead, bring the services back with the court-data switch and `--no-deps --force-recreate api worker
   worker2 scheduler web`. After the full rescore:
   - `SELECT count(*) FROM case_ownership WHERE actor_name = 'matching'` is 0;
   - `SELECT count(*) FROM case_office_scores WHERE engine_version NOT LIKE '3.%'` is 0;
   - `aslms insights status` shows `named_rescore_waiting` 0 within one `insights-refresh` run after the rescore.
5. Spot check: pick three cases from the dry run's withheld pairs (`aslms rescore --case REF --dry-run`). For each,
   confirm in Case Claim that no "Named in cause title" reason appears next to a keyword or name-pattern reason on the
   same respondent.

## Open questions
None. The owner's ruling of 21 Nov 2026 settles point 1. Decision 2's treatment of a phrase printed only in the cause
title is the conservative reading of that ruling and is laid out for the owner's approval with this note.

## Deviations
Choices the developer made where the note is silent (21 Nov 2026); none changes a business rule.

1. **`rescore_marked(..., stop_at=None)`** reads `stop_at` as the drain's cut-off: marks set at or before it are taken,
   newer ones wait. Its default is the database clock (`clock_timestamp()`) when the drain starts, as decision 10 says.
   Tests pass a time to check the cut-off.
2. **Party row 1** is the current respondent party row with the lowest party number (the rows are read in
   `party_no` order). A summary or cause-list respondent match records that row; when the case has no current
   respondent row, the match still counts as respondent evidence for the department (decision 2's second rule).
3. **Counters.** `build` returns `named_changed` as the number of rows it marked (no longer a list), and
   `rederive_departments(named_changed=...)` takes a small dictionary whose `"marked"` entry it increments. The drain's
   case count is `RunReport.rescored`, set after the run by the task, the CLI and `rebuild`; it is never stored in the
   `job_runs` counters (the drain runs after them).
4. **The refresh task** still returns None when another refresh held the lock (the drain runs first either way).
   `aslms insights refresh` without `--all` drains and then exits 1 in that case, as before.
5. **`--no-rescore`** prints the run's counters and then `marked for rescoring: N`, where N is the number of live cases
   carrying a mark (`insights_facts.marked_count`, the same count as `named_rescore_waiting`).
6. **`named_withheld`** counts only active Department-tier departments the row names with at least one phrase
   position; a department without a position (or a row with empty positions) gives no signal and is not counted as
   withheld.
7. **The clear statement** (`matching.CLEAR_MARK_SQL`) is one constant shared by `_score_one` and the drain.
8. **`named_rescore_waiting`** is a required field of `InsightsStatusOut`; `status()` always returns it.
