# Design: Case stages for appeal, review and contempt outcomes (case-stages-extension)

```
slug: case-stages-extension
status: approved
author: architect
date: 2026-10-13
approved_by: owner (nayanlhuzuri) on 2026-10-13
```

## Context
Backlog row 61. A department described how a case moves through its office in `docs/Case_Handling.docx`
(13 Oct 2026). The decisions log entry "Department input: Case_Handling.docx (13 Oct 2026)" records the owner's
decision: add the stages that are missing, as a reference-data migration. The document's steps that have no stage
today are these:
- **B, Option B, Appeal/Review.** The department may file a *review petition* as well as an appeal. Only
  `appeal_under_consideration` and `appeal_filed` exist today.
- **B, Option C, Subsequent action.** The appeal or review is *dismissed* or *allowed*. After a dismissal the
  department either *complies* or files a *further appeal before the higher court*.
- **C, Contempt.** On a contempt notice, the respondent *submits the signed Vakalatnama* to the Standing Counsel
  (§10). The *contempt case is then disposed* (§11). Only `contempt_notice` and `contempt_reply_filed` exist today.

**In place already** (custody-workflow, decision 19; portal-workflow, decision 9):
- `ref_case_stage` holds 17 codes in four phases (`main`, `counsel`, `appeal`, `contempt`), seeded from the
  `Stage` enum by `aslms seed`.
- `case_stages` is append-only. Its latest row is the current stage. Stages are guided, not enforced.
- `POST /cases/{ref}/stages` (`stages.set`) accepts any active code. `GET /workflow/codes` lists the active
  stages with phase and `sort_order`.
- The portal's Set stage dialog and the Send file dialog group the stages by phase, in `sort_order`.
- Gaps are computed only over `main`-phase stages.

So new codes need only the rows and the Python enum members. No screen, endpoint or rule changes.

**Not covered:** alerts to the officer named in a contempt case (row 62, parked); finding contempt cases by
officer names (row 19, department discovery); any automatic stage setting (no stage is ever set by the system);
any behaviour tied to a stage (for example, stopping compliance alerts once "Contempt disposed" is recorded). The
plan gives no rule for that, so none is added.

## Decisions
1. **Seven new codes, in the order the owner listed them:**

   | code | label | phase | sort_order |
   |---|---|---|---|
   | `review_petition_filed` | Review petition filed | appeal | 180 |
   | `appeal_dismissed` | Appeal or review dismissed | appeal | 190 |
   | `appeal_allowed` | Appeal or review allowed | appeal | 200 |
   | `further_appeal_filed` | Further appeal filed (higher court) | appeal | 210 |
   | `complied_after_dismissal` | Complied after dismissal of appeal or review | appeal | 220 |
   | `vakalatnama_submitted` | Vakalatnama submitted | contempt | 230 |
   | `contempt_disposed` | Contempt disposed | contempt | 240 |

   - *Alternatives:* separate `review_dismissed` / `review_allowed` codes (rejected: codes the owner did not list);
     labels "Appeal dismissed" / "Appeal allowed" exactly as the backlog words them.
   - *Reason for the "or review" labels:* Case_Handling.docx Option C speaks of "the Appeal/Review is dismissed",
     and the owner's own "complied after dismissal of the appeal/review" assumes a dismissed review can be
     recorded. With "Appeal dismissed" a review petition would have a filed stage and no outcome stage.
   - The codes stay `appeal_dismissed` / `appeal_allowed`. This is a wording choice, put to the owner at approval
     (labels are data and can be changed later without a release).
2. **Ordered after the existing codes (sort_order 180–240, after `closed` at 170). Existing rows are not renumbered.**
   - *Alternative:* interleave inside each phase, for example `vakalatnama_submitted` at 155 between
     `contempt_notice` and `contempt_reply_filed`. Rejected: the backlog row says "ordered after the existing
     codes", and the seed assigns `sort_order` as position × 10 in the enum. Interleaving would need a separate
     override map that must be kept in step with the migration.
   - The dialogs group by phase, so in practice each new code appears at the end of its own phase group (appeal:
     2 + 5; contempt: 2 + 2). `closed` stays in the main group. Gaps are unaffected, because they count only
     `main` stages.
3. **Phases follow the backlog row.** The first five are `appeal`; Vakalatnama and contempt disposed are
   `contempt`. No new phase is added. *Alternative:* a `review` phase (rejected: the department document treats
   appeal and review as one track).
4. **A reference-data migration, 0016, as the owner decided, and the seed carries the same rows.**
   - Until now new `ref_*` codes were seed rows only (0003, 0004, 0007, 0009 say so). This is a change of project
     convention at the owner's request, **not a deviation from the plan** (the plan does not list stages).
   - The migration inserts the seven rows with `ON CONFLICT (code) DO NOTHING`. The dev database, which is
     already seeded and running the load, gets them on `alembic upgrade head` without a re-seed.
   - The `Stage` enum gains the seven members at its end, which is needed because `case_stages.stage` loads as
     `Stage` and `check_stage` parses `Stage(raw)`.
   - `aslms seed` gets the same labels and phases. Whichever runs first (the migration on a seeded database, or
     the seed on a wiped one in the tests) produces identical rows, and a test proves it.
   - The migration hard-codes its rows and does not import application code, so applied migrations stay frozen.
5. **No `description` text** (NULL, like the 17 existing rows). Neither dialog shows descriptions. *Alternative:*
   quoting Case_Handling.docx (rejected: it adds a second copy to keep in step and is never displayed).
6. **No audit row for the migration.** Audit covers application actions (configuration changes made from the
   application). A release step writes no `audit_log` row, like the seed. Recording a new stage on a case is
   audited as today (`stage.set`, `stage_set` event).
7. **The downgrade is guarded.**
   - It refuses while any `case_stages` row uses one of the seven codes. These are legal-record history, and FK
     RESTRICT would stop it anyway; the guard gives a clear message, like the 0010 guard.
   - Otherwise it deletes the seven reference rows. Deleting is chosen over `is_active = false` so that a later
     re-upgrade (`ON CONFLICT DO NOTHING`) does not leave them inactive.
8. **No API, permission, screen or frontend change.** `GET /workflow/codes`, `POST /cases/{ref}/stages`, the Send
   file stage choice, the Custody and stage tab and the overview read the catalogue. The phase shows as its code
   ("appeal", "contempt"), as today.

## Data
No table or column is added or changed. Reference codes go into `ref_case_stage`. The **migration is 0016**
(`backend/migrations/versions/0016_case_stages.py`, revision `0016`, down-revision `0015`, a new file; no applied
migration is edited).

**Upgrade:**
```sql
INSERT INTO ref_case_stage (code, label, phase, sort_order, is_active) VALUES
 ('review_petition_filed', 'Review petition filed', 'appeal', 180, true),
 ('appeal_dismissed', 'Appeal or review dismissed', 'appeal', 190, true),
 ('appeal_allowed', 'Appeal or review allowed', 'appeal', 200, true),
 ('further_appeal_filed', 'Further appeal filed (higher court)', 'appeal', 210, true),
 ('complied_after_dismissal', 'Complied after dismissal of appeal or review', 'appeal', 220, true),
 ('vakalatnama_submitted', 'Vakalatnama submitted', 'contempt', 230, true),
 ('contempt_disposed', 'Contempt disposed', 'contempt', 240, true)
ON CONFLICT (code) DO NOTHING;
```
- The rows are a module-level tuple `NEW_STAGES` (code, label, phase, sort_order), so the test can compare them
  with the seed.
- No grant is needed: `aslms_app` already has SELECT / INSERT / UPDATE on `ref_case_stage` (0001).
- `created_at` / `updated_at` take their defaults.

**Downgrade:**
- If `SELECT count(*) FROM case_stages WHERE stage IN (<the seven>)` > 0, raise
  `RuntimeError("cannot downgrade 0016: N case_stages row(s) use the added stages; the stage history would be lost")`.
- Otherwise `DELETE FROM ref_case_stage WHERE code IN (<the seven>)`.

**`docs/schema/schema.md`, Group 0.** Replace the `ref_case_stage` row's Notes with:

> The lifecycle stages in order (reference class; `code` PK; `case_stages.stage` → RESTRICT). 17 seeded from
> `Stage`, then 7 added by `case-stages-extension` (migration 0016, a reference-data migration: `ON CONFLICT DO
> NOTHING`, the seed carries the same labels and phases): `review_petition_filed`, `appeal_dismissed` ("Appeal or
> review dismissed"), `appeal_allowed` ("Appeal or review allowed"), `further_appeal_filed` ("Further appeal filed
> (higher court)"), `complied_after_dismissal` (phase `appeal`, sort 180–220); `vakalatnama_submitted`,
> `contempt_disposed` (phase `contempt`, sort 230–240). 24 rows, all active. Gaps count only `main` stages.

In the "Code sets" paragraph, after "the seed upserts one row per member", add: "(`ref_case_stage`'s seven
appeal and contempt codes also come from migration 0016)". `DB_STANDARD.md` is not edited: its "17 values" is the
historical enum-to-table conversion table.

## Services
- **`backend/aslms/domain/reference.py`:** append to `Stage`, after `CLOSED` and in this order,
  `REVIEW_PETITION_FILED`, `APPEAL_DISMISSED`, `APPEAL_ALLOWED`, `FURTHER_APPEAL_FILED`,
  `COMPLIED_AFTER_DISMISSAL`, `VAKALATNAMA_SUBMITTED`, `CONTEMPT_DISPOSED`. Position decides the seed's
  `sort_order` (18–24 × 10 = 180–240). No member is retired.
- **`backend/aslms/services/seed.py`:**
  - `STAGE_PHASE` gains the five `appeal` and two `contempt` members.
  - A new `STAGE_LABELS` holds the labels that differ from the generated one (`appeal_dismissed`,
    `appeal_allowed`, `further_appeal_filed`, `complied_after_dismissal`).
  - `_extra_columns` for `RefCaseStage` returns `{"phase": ..., "label": ...}` when the member is in
    `STAGE_LABELS`.
  - The seed still only inserts missing codes. It never relabels or reorders existing rows.
- **`backend/aslms/services/stages.py`:** the module docstring's "one track of the 17 stages" becomes "one track
  of the stages in `ref_case_stage`". There is no logic change. `check_stage`, `set_stage` (stage-row lock,
  `stage_set` event with phase, `stage.set` audit), `compute_gaps` and `catalogue` work unchanged on the new codes.
- No other module changes. `workflow_codes.codes`, the custody send's `check_stage`, the case overview and
  `history_with_gaps` read the catalogue.

## API
No endpoint is added or changed. The existing endpoints simply carry the new codes:
- `GET /workflow/codes`: `cases.view_scope` or `cases.view_all`. `stages` lists 24 active codes with `phase` and
  `sort_order`, the same for every reader (reference data).
- `POST /cases/{ref}/stages`: `stages.set`, plus a working basis on a claimed, visible case (custody-workflow
  decision 9). It accepts the seven codes. Unknown codes → 400 as today.
- `GET /cases/{ref}/stages`: `cases.view_scope` or `cases.view_all`, server-side visibility as today. `gaps` is
  `[]` when the current stage is one of the seven (not `main`).
- `POST /cases/{ref}/custody/send` with `stage`: `custody.move`, plus `stages.set` for the stage, as today.

## Jobs
None.

## Tests
- **Unit** (`tests/unit/test_case_stages_extension.py`):
  - `test_stage_enum_appends_seven_codes_after_closed`: 24 members; the last seven in the order of decision 1;
    every value ≤ 40 characters.
  - `test_seed_phase_and_labels_for_new_stages`: `_extra_columns(RefCaseStage, m)` gives the decision-1 phase and
    label for each of the seven, and leaves the 17 existing members' outputs unchanged.
  - `test_new_stages_never_count_as_gaps`: `compute_gaps` over a catalogue with the new appeal / contempt entries
    returns `[]` when one of them is current, and never lists them when a `main` stage is current.
- **Database** (`tests/db/test_migration_0016.py`, following the pattern of `test_migration_0015.py`):
  - `test_0016_inserts_the_seven_rows_on_an_empty_table`: wipe, downgrade to 0015, upgrade to 0016 → exactly
    the seven rows with the decision-1 code, label, phase, sort_order and `is_active`.
  - `test_seed_and_migration_produce_the_same_rows`: after the migration, `seed_all` inserts the 17 others and
    leaves the seven untouched. A wiped database seeded without the migration gives the same seven rows. The
    migration module's `NEW_STAGES` equals the seed's output.
  - `test_0016_after_seed_is_a_no_op`: seed at 0015 with the new code (24 rows), upgrade to 0016 → no error,
    still 24 rows, labels unchanged.
  - `test_0016_downgrade_refuses_while_a_case_stage_uses_a_new_code`: with a `case_stages` row at
    `vakalatnama_submitted`, downgrade raises and keeps all rows. Without it, the downgrade deletes the seven,
    keeps the 17, and the re-upgrade restores them active.
  - `test_models_match_head`: `compare_metadata` is clean at head (non-native enum `modify_type` ignored, as in
    0015).
- **Database / API:**
  - `tests/db/test_api_workflow.py::test_codes`: `len(body["stages"]) == 24`, and the seven are present with
    their phases.
  - New: `test_set_new_contempt_stage`. `POST /cases/{ref}/stages` with `vakalatnama_submitted` by a `stages.set`
    holder on a claimed case → 201. Then `GET` shows current phase `contempt` and `gaps == []`. One `stage_set`
    event with `phase: "contempt"` and one `stage.set` audit row.
  - New: `test_set_new_appeal_stage_through_send`. A custody send with `stage: "appeal_dismissed"` records it.
- **Existing:** `test_seed_and_refno.py::test_seed_twice_inserts_nothing_the_second_time` must stay green (count
  == `len(Stage)` == 24). The frontend tests need no change (they use mock codes).

## Verification
1. `ruff check` clean; `pytest -q` green.
2. Dev database: run `docker compose run --rm init` (`alembic upgrade head && aslms seed`). Then
   `select code, label, phase, sort_order from ref_case_stage order by sort_order` gives 24 rows, the last seven
   exactly as in decision 1. `alembic current` = `0016`. A second `aslms seed` reports 0 inserted.
3. `GET /workflow/codes` as a department officer → 24 stages.
4. Portal (Compose `web`) on a claimed case: open Set stage. The appeal group lists Appeal under consideration,
   Appeal filed, then the five new codes. The contempt group lists Contempt notice, Contempt reply filed,
   Vakalatnama submitted, Contempt disposed.
5. Set "Vakalatnama submitted". The Custody and stage tab shows it with "contempt" and no gaps. The audit search
   (`GET /audit`) shows the `stage.set` row.
6. The running historical load is not affected (no table or lock change; the insert touches only
   `ref_case_stage`).

## Open questions
None. The labels in decision 1 ("Appeal or review dismissed / allowed") are a wording choice for the owner to
confirm or change at approval. They do not block the build.

## Deviations
Recorded by the developer while building (none changes the plan or a decision above).
1. Migration 0016 is written by hand: it changes no table, so `alembic revision --autogenerate` has nothing to
   generate. It runs one parameterised `INSERT … ON CONFLICT (code) DO NOTHING` per row of `NEW_STAGES` instead of
   one multi-row `VALUES` statement (same effect), and the downgrade's guard and delete use `= ANY(:codes)`.
2. `test_0016_after_seed_is_a_no_op` also edits one seeded label before the upgrade and checks the edit survives
   (`ON CONFLICT DO NOTHING` never relabels). A unit test `test_migration_rows_equal_the_seed` compares the
   migration's `NEW_STAGES` with the seed's output without a database, next to the database comparison.
