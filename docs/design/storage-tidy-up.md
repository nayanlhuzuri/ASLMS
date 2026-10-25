# Design: Storage tidy-up (one verbatim copy per NAPIX answer)

```
slug: storage-tidy-up
status: approved
author: architect
date: 2026-10-25
approved_by: owner on 2026-10-25, with the recommended answers except c: no compression change at all (no lz4 anywhere, no toast target change), because the measured difference is not worth it
```

## Context
Backlog row 156 comes from the read-only database audit of 25 Oct 2026 (decisions log, "Database audit; backups off
in development; old folders kept"). The owner approved the direction the same day. The audit found that the dev
database (2.6 GB) stores the same NAPIX case data three or four times. That copy is the main steady grower. The
audit also found two indexes that are never used, and many `order_stored` events written for backfill PDFs.

**The rules this item must keep.**
- CLAUDE.md: "Every NAPIX field is kept. Each API response is stored verbatim as JSON, and every documented or observed
  field has a typed home in the schema."
- DB_STANDARD §6: rows of legal significance are never deleted. The `napix_call_log` purge is the only exception.
- Applied migrations are never edited. `napix_responses` is never purged (design `court-data-freshness`, decision 21).

**A conflict with the plan's addendum, flagged.** The coverage addendum (`docs/schema/napix_coverage.md`, "1.
Verbatim") names the verbatim homes:
- `case_snapshots.payload` for the CNR dossier and Current Status;
- `napix_responses` for every other JSON answer.

The code does something else. `NapixRecorder` (`services/napix_store.py`) stores **every** answer in
`napix_responses`, including CNR and Current Status. `services/cases.py` then copies the same data three more times:
- into `case_snapshots.payload` (`_snapshot`);
- into `cases.raw` (`apply_dossier`, line 709);
- into `orders.raw` (`_sync_orders`, line 488).

So the CNR dossier has two verbatim homes, not one, plus two more copies. Decision 1 resolves this with one verbatim
home, and amends the addendum and DB_STANDARD §10 through this note.

**What the dev data says.** Read-only queries on 25 Oct 2026, database `aslms` at migration 0025, PostgreSQL 16.15.
Counts grow while the historical load runs.

| Copy | Rows | Stored size | Notes |
|---|---|---|---|
| `napix_responses.payload` | 64,613 | 130 MB (382 MB as text) | the single home we keep; CNR 59,297 rows / 107 MB; Current Status 722 rows / 21 MB (116 MB as text, about 95 cases per answer) |
| `case_snapshots.payload`, source `cnr` | 59,245 | 107 MB | **every one** equals a stored `hc-cnr-api/CNR` answer: same sha256 and jsonb-equal (59,245 of 59,245) |
| `case_snapshots.payload`, source `current_status` | 68,855 | 44 MB (inline, not compressed) | **every one** equals one block (`cases<n>`) of a stored Current Status answer for that case's CNR (68,855 of 68,855) |
| `cases.raw` | 54,117 | 97 MB | **every one** equals a CNR snapshot of the same case (54,117 of 54,117); nothing reads it |
| `orders.raw` | 303,865 | 63 MB | the order row of the dossier. Its six keys all have typed columns: `order_no`, `order_date`, `order_details`, `order_judge_name`, `date_judgement_pronounced`, `date_judgement_reserved`. A sample of 3,000 of 3,000 was found inside a stored CNR answer of the case. Nothing reads it |

- The duplicate copies total **311 MB** of stored values: 151 MB in snapshots, 97 MB in `cases.raw` and 63 MB in
  `orders.raw`. With their row and index overhead, the tables can shrink by about 340 MB (see "Expected savings"
  below).
- **Table sizes:** `case_snapshots` 238 MB, `cases` 255 MB, `orders` 197 MB, `napix_responses` 191 MB, `events`
  226 MB, `fetch_queue` 225 MB, `causelist_entries` 223 MB, `document_text` 563 MB.

**What this item does not cover.**
- The small `raw` columns of `case_applications`, `case_lower_courts`, `case_objections`, `case_transfers`,
  `case_writ_info` and `causelists` stay as they are: 102 non-empty values and about 1.7 MB together.
- `document_text.search_vector` (272 MB) is not touched.
- Act and advocate name resolution is row 155.
- Backups were handled on 25 Oct (profile `backup`).

## Decisions

1. **One verbatim copy per answer, in `napix_responses`; `case_snapshots` points to it.** A snapshot row keeps
   `case_id`, `source`, `fetched_at`, `last_seen_at` and `payload_sha256` (the sha256 of the case's own block, as
   today). Two new columns say where the block is:
   - `response_id` (→ `napix_responses`);
   - `payload_key`: the block's top-level key inside a Current Status answer, such as `cases12`. It is NULL when the
     block is the whole answer, as for a dossier.

   `payload` becomes nullable. It is kept only when no stored answer holds the block, so nothing verbatim can be
   lost. Rejected alternatives:
   - **The reverse**, with `napix_responses` pointing to `case_snapshots`. One Current Status answer covers up to 300
     cases, and `napix_responses` holds all 14 APIs, not only these two.
   - **`case_snapshots` as the only home for CNR and Current Status**, the addendum's letter. The recorder would have
     to skip two APIs. The System health inspector, which reads `napix_responses`, would lose them. Each Current
     Status answer would be split into blocks, and the answer as received (its key order and its unknown top-level
     keys) would no longer be kept as one object.

   Why `napix_responses`:
   - it already holds 100% of these blocks;
   - it deduplicates by (api, params_sha256, payload_sha256);
   - it carries the call's context (`params`, `token_verified`, `job_run_id`);
   - it is never purged.

   **Amendment of the coverage addendum and DB_STANDARD §10** (owner approval through this note; texts under
   "Data").

2. **The block is rebuilt exactly.** A snapshot's block is
   `COALESCE(s.payload, CASE WHEN s.payload_key IS NULL THEN r.payload ELSE r.payload -> s.payload_key END)`. Its
   sha256, computed with `napix_store.payload_sha256`, equals `s.payload_sha256`.
   - The writer checks this before it stores a reference (Services). If the check fails, it stores the payload
     instead.
   - The helper `cases.snapshot_block(session, snapshot)` returns the block. The code has no other reader of snapshot
     payloads today.

3. **The single home cannot change.** `napix_responses` gets the trigger `napix_responses_frozen`:
   `BEFORE UPDATE OF api, params_sha256, params, payload_sha256, payload, fetched_at`, running the existing
   `aslms_forbid_change()`.
   - The recorder's `ON CONFLICT … DO UPDATE SET last_seen_at = now()` still works.
   - `aslms_app` already has no DELETE on the table.
   - The RESTRICT key from `case_snapshots` makes a referenced answer undeletable even by mistake.
   - Rejected: no trigger. With one copy, a wrong UPDATE would lose the only verbatim record.

4. **How the writer learns the answer's id, and why it must not deadlock.** Today the recorder writes answers only
   at `flush`. That happens after `apply_dossier` in the queue runner and in the API request paths, where the apart
   session commits after the case work. If the request session inserted the `napix_responses` row itself, the
   apart flush would insert the same unique key from a second connection. It would then wait on the request's
   uncommitted row while the request waits for it, which is a self-deadlock. So we add
   `NapixRecorder.store_now(session, result) -> uuid.UUID`. It writes that one answer at once, through the existing
   `store_response`:
   - **with a session factory (request paths):** in an apart session that it commits at once, so the request session
     only references a row that is already committed;
   - **without one (queue runner):** in the item's session.

   The later flush's upsert finds the same row and only bumps `last_seen_at`. The call-log rows are not touched and
   stay pending for the normal flush. If a runner item fails and rolls back, the recorder's flush still writes the
   answer, so nothing is lost. The result comes from `NapixHighCourt.last`, which already exists. Rejected
   alternatives:
   - **flushing the whole recorder mid-item:** after the runner's rollback, a failed item would lose its call-log
     rows;
   - **a composite key on (api, params_sha256, payload_sha256) without an id:** it needs a deferred FK, and the apart
     ordering still bites.

5. **`cases.raw` and `orders.raw` are no longer written**, and their existing values are emptied after a check. The
   columns stay, with a `COMMENT` that says so. Nothing reads them: `grep` finds only the two writers, and
   `test_case_detail.py` already leaves `raw` out.
   - A value becomes NULL only where the same content is verified inside a stored answer of the case: the whole CNR
     answer for `cases.raw`, and an element of `interimorder` or `finalorder` (object or array form) for
     `orders.raw`.
   - A value that cannot be verified is kept.
   - This is not a deletion of a legal record. The row stays, every typed column stays, and the verbatim content
     stays in `napix_responses`.
   - Rejected: **stop writing but keep the values.** That leaves 160 MB in place for nothing.
   - Rejected: **drop the columns.** That needs a later, irreversible migration. It can be considered after the
     pilot.

6. **The data step is a batched command, not part of the migration.** Migration 00NN changes only the schema: DDL
   and catalog changes that take seconds. The existing rows are moved by `aslms ops storage-tidy`:
   - a dry run by default; `--apply` to act;
   - batches of 5,000 rows, each committed on its own;
   - resumable and idempotent, safe while the worker runs.

   The migration's downgrade restores every emptied value from `napix_responses` before it removes the columns, so
   the whole change is reversible. Precedents: `aslms data-load pdfs-after-details --apply`, and `aslms
   close-claimed-recommendations` after migration 0021. Rejected: a data migration in one transaction. About 480,000
   row updates under the `migrate` lock, with no progress or resume.

7. **Snapshots heal themselves.** When a fetch brings a block whose snapshot row exists with its own `payload` and
   no `response_id`, the writer sets `response_id` and `payload_key` and clears `payload`. This covers rows the
   command could not match. Dev has none, but a database restored from an older dump could.

8. *Owner, 25 Oct 2026: **no compression change at all.** The lz4 switch on `document_text.full_text` below is dropped; no column's compression or toast target changes. The measurements below stay for the record.*

   8. **Compression: lz4 only for `document_text.full_text`, and no `toast_tuple_target` change. This deviates from
   the backlog wording, with measurements.**

   Real values exported read-only from dev (5,000 cause-list rows, 5,000 order rows, 3,000 dossiers, 150 Current
   Status answers, 5,000 status blocks, 3,000 document texts, 5,000 event payloads) were inserted into a throwaway
   PostgreSQL 16.15 container. That container is not the dev database, and it has been removed. Results:

   | Values | pglz | lz4 | Insert time pglz → lz4 |
   |---|---|---|---|
   | CNR answers (the bulk of `napix_responses`) | 5.68 MB | 6.41 MB (**+12.7%**) | 268 → 122 ms |
   | Current Status answers | 4.50 MB | 4.30 MB (−4.4%) | 433 → 184 ms |
   | `document_text.full_text` | 5.66 MB | 5.65 MB (same) | 19 → 20 ms |
   | cause-list `raw`, order `raw`, status blocks, event payloads | not compressed with either | not compressed | — |

   - **lz4 saves CPU, not space.** On `napix_responses.payload` it would add about 13 MB on dev (CNR 107 → 121 MB,
     status 21 → 20 MB), so that column stays pglz.
   - **`document_text.full_text` switches to lz4.** The size is the same, and lz4 reads much faster for content-search
     snippets and the next-date reader. The change is catalog-only and applies to new values. Existing pglz values
     stay readable; PostgreSQL reads mixed methods.
   - **`toast_tuple_target` at 1024, 512 or 256 changed nothing.** The same rows were compressed in every case: 4 of
     5,000 cause-list rows and 0 of 5,000 status blocks. PostgreSQL 16 starts toasting only when a row exceeds the
     fixed `TOAST_TUPLE_THRESHOLD` (about 2 KB). The reloption only sets how far it then shrinks. The rows that waste
     space (cause-list entries about 1.4 KB, status blocks about 650 bytes, order rows about 200 bytes) are all below
     it, so the setting is left at its default.
   - **No one-time recompression rewrite.** Rewriting existing values to lz4 gains no space. `VACUUM FULL` does not
     recompress either. The only rewrite worth a window is the `VACUUM FULL` that returns the freed space (decision
     12).

9. **Drop the two never-used indexes and keep every uniqueness index.**
   - `ix_case_parties_name_normalised` (13 MB): `idx_scan` is 0 since the cluster was initialised
     (`pg_stat_database.stats_reset` is NULL). The only query on the column is
     `CaseParty.name_normalised.like('%…%')` (`services/data_load.py`, line 1242). A B-tree cannot serve a leading
     wildcard, and no code compares the column for equality or a prefix.
   - `ix_case_snapshots_case_id` (3.5 MB): `idx_scan` was 0 before this design's own read-only check. That check ran
     `s.case_id = c.id` once for each of 54,117 cases, and the planner took the smaller index. Every lookup by
     `case_id` is served by `uq_case_snapshots_case_id_payload_sha256` (case_id, payload_sha256), whose leading
     column is `case_id`. It had 242,222 scans; the writer's own lookup uses both columns.
   - Kept: `uq_case_snapshots_case_id_payload_sha256`, `pk_case_snapshots`, and every unique and primary key.
   - The models change to `index=False` (`CaseSnapshot.case_id`, `CaseParty.name_normalised`), so metadata and
     migrations agree.

10. **Order events are written only for live and request work. This deviates from the backlog wording, with
    evidence.** The backlog says "stop `order_stored` events for backfill PDFs (load lane)". In dev, **all 137,661
    order-PDF queue rows are in the `daily` lane**, including those for list dates from January 2025. The weekly
    never-fetched sweep and the lane precedence (`LEAST`) lift the load's rows into `daily`. So a lane rule would save
    almost nothing.

    The rule that matches what alerts use: `order_found` (in `enqueue_order_pdfs`) and `order_stored` (in
    `fetch_order_pdf`) are written when either
    - the work is in the `request` lane, or
    - the order's date is within `ALERT_EVENT_MAX_AGE_DAYS` (default 14) of today IST, by
      `alert_rules.is_recent`, the same test the alert scan applies before it raises `new_order`.

    So no alert is lost: `order_stored` events for older orders are skipped by the scan today (`skipped_old`), and
    `order_found` raises no alert at all. In dev, 8,087 of 303,865 `order_found` and 6,324 of 137,653 `order_stored`
    events meet the date test. That is **97% fewer** order events going forward. No `alerts` row in dev comes from an
    order event.

    Effects:
    - The case timeline no longer gets "order found" or "stored" lines for old orders. The Orders tab lists every
      order with its PDF and stays the record.
    - Existing events are never deleted (`events` is append-only).
    - Rejected: the lane rule as worded. It saves nothing on today's data.

11. **`causelist_entries.raw` is slimmed for new rows only.** The column holds the parser's output, not NAPIX data.
    That is every `Entry` field, including `raw_lines`, which exists **only** inside `raw`; there is no `raw_lines`
    column.
    - New rows keep only:
      - the fields without a typed column: `page`, `is_filing_number`, `pet_advocates`, `res_advocates`,
        `pet_counsel_codes`, `res_counsel_codes`, `raw_lines`;
      - the parser's original value of any typed field that `entry_values` truncated (`court_no` to 20, `section` and
        `case_no_text` to 200, a counsel code to 60), so nothing the parser read is lost.
    - Measured on 5,000 dev rows: 980 → 442 bytes on average (**−55%**).
    - Existing rows are untouched, because entries are "immutable once written" (schema.md). No reader uses `raw`, and
      the list fingerprint leaves it out.
    - Rejected: **stop writing `raw`.** `raw_lines` is the only text-level record of the printed row besides the PDF.
    - Rejected: **rewrite old rows slim.** That edits immutable rows for 74 MB.
    - Rejected: **compress through TOAST.** It is not possible below 2 KB (decision 8).

12. **Finished `fetch_queue` rows: no purge in this item.** There are 182,939 `done` rows: 52 MB of rows plus their
    share of 110 MB of indexes.
    - **The documents conflict.** The coverage addendum §A says `done` rows "may be pruned like `napix_call_log`". The
      later as-built text in schema.md (safety-fixes) says "`fetch_queue` stays class `derived`, with RESTRICT keys
      and no DELETE". DB_STANDARD §6 names only the call-log purge as an allowed deletion.
    - **So a queue purge needs an owner exception, and it would change behaviour:**
      - a `done` row is the queue's dedupe, so the load does not fetch the same day or dossier again (`enqueue` revives
        `done` rows only with `requeue`);
      - the data-load console, data-health, the load report and the data-health report count `done` rows by lane and
        list date.
    - Recommendation: keep them, and amend the addendum's sentence to match schema.md. Revisit after the historical
      load finishes, as a new row if the owner wants it (for example, trimming `result` jsonb of old `done` rows,
      30 MB).

13. **Returning the space** (operations). After `--apply`, autovacuum makes the freed space reusable inside the
    tables, with no downtime; growth fills it first. To shrink the files, run
    `VACUUM (FULL, ANALYZE) case_snapshots, cases, orders` in a short maintenance window. It takes an ACCESS
    EXCLUSIVE lock, so `api`, `worker` and `scheduler` are stopped, and it is run as `POSTGRES_USER`.
    - A 537 MB scratch table with two indexes took 2 s on the dev machine. The three tables (690 MB) should take well
      under a minute; the integrator records the real time (Verification).
    - Doing this in dev is the owner's choice. For the pilot, the runbook gets a section.

14. **Migration number:** the next free number after the migrations of rows 153 and 154. That is **0028** if they
    land as 0026 and 0027. It is set at build time and recorded, with no number reserved (precedent rows 122, 135
    and 153). Hand-written.

## Data

**Migration 00NN `00NN_storage_tidy_up.py`** (expected 0028; revises whichever of rows 153 and 154 is head).

Upgrade, one transaction, schema only:
1. `case_snapshots`:
   - `ADD COLUMN response_id uuid NULL`, with `fk_case_snapshots_response_id_napix_responses` → `napix_responses(id)`
     `ON DELETE RESTRICT`;
   - `ADD COLUMN payload_key varchar(40) NULL`;
   - `ALTER COLUMN payload DROP NOT NULL`;
   - `ADD CONSTRAINT ck_case_snapshots_payload_home CHECK (payload IS NOT NULL OR response_id IS NOT NULL)`;
   - `ADD CONSTRAINT ck_case_snapshots_payload_key CHECK (payload_key IS NULL OR response_id IS NOT NULL)`.

   Both CHECKs are valid at once, because every row has a payload.
2. `DROP INDEX ix_case_snapshots_case_id`; `DROP INDEX ix_case_parties_name_normalised`.
3. ~~`ALTER TABLE document_text ALTER COLUMN full_text SET COMPRESSION lz4`~~ dropped by the owner (no compression change).
4. `CREATE TRIGGER napix_responses_frozen BEFORE UPDATE OF api, params_sha256, params, payload_sha256, payload,
   fetched_at ON napix_responses FOR EACH ROW EXECUTE FUNCTION aslms_forbid_change()`.
5. `COMMENT ON COLUMN cases.raw` and `orders.raw`: "Not written since migration 00NN (design storage-tidy-up); the
   verbatim answer is in napix_responses." Also a comment on `case_snapshots.payload`.

Downgrade, the mirror, which restores data first:
1. Snapshot payloads: `UPDATE case_snapshots s SET payload = CASE WHEN s.payload_key IS NULL THEN r.payload ELSE
   r.payload -> s.payload_key END FROM napix_responses r WHERE r.id = s.response_id AND s.payload IS NULL`.
2. `cases.raw` where NULL: the block of the case's CNR snapshot with the newest `last_seen_at`. That is the last
   dossier applied, because `_snapshot` bumps `last_seen_at` on every re-apply, so it equals what `apply_dossier`
   last wrote.
3. `orders.raw` where NULL: the `interimorder` or `finalorder` element with the same `order_no` and
   `order_date` text (`to_char(order_date, 'YYYY-MM-DD')`), from the newest CNR snapshot of the case that holds it.
   It stays NULL if no answer holds it, which was already allowed.
4. Drop the trigger. `SET COMPRESSION default` on `full_text`. Recreate the two indexes. Drop the two CHECKs and the
   two columns. `SET NOT NULL` on `payload`, which fails loudly if step 1 left a NULL; it cannot, by the CHECK.

No new grant. `aslms_app` already has UPDATE on `case_snapshots`, `cases` and `orders`. No new `ref_*` code. The
audit action `system.storage_tidied` is free text, like `system.migrated`.

**schema.md**: the `case_snapshots` row is replaced by this paragraph.

> | `case_snapshots` (derived) | id, case_id (→ cases RESTRICT), source (`cnr` / `current_status`), fetched_at, last_seen_at, payload_sha256 (sha256 of the case's block, `napix_store.payload_sha256`), response_id uuid NULL (→ napix_responses RESTRICT: the stored answer holding the block), payload_key varchar(40) NULL (the block's top-level key inside a Current Status answer, e.g. `cases12`; NULL when the block is the whole answer), payload jsonb NULL (the block itself, kept only when no stored answer holds it), created_at | Unique (case_id, payload_sha256), which also serves every lookup by case_id (`ix_case_snapshots_case_id` dropped by 00NN). CHECKs `ck_case_snapshots_payload_home` (`payload IS NOT NULL OR response_id IS NOT NULL`) and `ck_case_snapshots_payload_key` (`payload_key IS NULL OR response_id IS NOT NULL`). The block is `COALESCE(payload, CASE WHEN payload_key IS NULL THEN r.payload ELSE r.payload -> payload_key END)` and hashes to `payload_sha256` (`cases.snapshot_block`). No index on response_id: answers are never deleted, and reads go from snapshot to answer by primary key. Written only by `services/cases.py::_snapshot` and `aslms ops storage-tidy` (design storage-tidy-up). Diffing successive snapshots produces status and next-date change events. |

**schema.md, as-built note** (appended at build):

> As built by `storage-tidy-up` (migration 00NN; revises 00NN−1): `case_snapshots` gains `response_id` and
> `payload_key`, `payload` becomes nullable, and two CHECKs are added. The trigger `napix_responses_frozen`
> (`aslms_forbid_change()` on UPDATE of api, params_sha256, params, payload_sha256, payload, fetched_at) makes a stored
> answer unchangeable; only `last_seen_at` moves. `cases.raw` and `orders.raw` are no longer written; they are emptied
> by `aslms ops storage-tidy` where the value is verified inside a stored answer, and kept otherwise.
> `causelist_entries.raw` of new rows holds only the parser fields without a typed column and any truncated original.
> `document_text.full_text` uses lz4 for new values. `ix_case_snapshots_case_id` and `ix_case_parties_name_normalised`
> are dropped. No toast reloption: measured to have no effect below 2 KB rows. The downgrade restores every emptied
> value from `napix_responses` first.

The convention line in schema.md, "Data received from NAPIX is kept verbatim in a `raw jsonb` column beside the parsed
columns", becomes: "Every JSON answer from NAPIX is kept verbatim once, in `napix_responses.payload`; `case_snapshots`
names the answer and block it comes from. The small `raw` columns of the dossier's child tables keep their row;
`cases.raw` and `orders.raw` are no longer written (storage-tidy-up)."

**Coverage addendum amendment** (`docs/schema/napix_coverage.md`):
- Point 1, "Verbatim", becomes: "Every JSON response is kept as the court sent it, once, in the derived table
  `napix_responses` (one row per distinct answer). `case_snapshots` is the case's history of its dossier and Current
  Status blocks: each row names the answer (`response_id`) and, for a Current Status block, its key in it
  (`payload_key`). A snapshot keeps its own `payload` only when no stored answer holds the block. PDFs go to
  `documents` (content-addressed). *(Amended 25 Oct 2026 by design storage-tidy-up, owner approval; the 1 Oct text
  named `case_snapshots.payload` as the home of the dossier and Current Status.)*"
- The rows "*(whole dossier / status block)* | `case_snapshots.payload`" become "`napix_responses.payload` (the
  case's block named by `case_snapshots.response_id` / `payload_key`)".
- The `case_snapshots` row in §A reads "the case's dossier and status history; the block lives in `napix_responses`".
- The `fetch_queue` row's last sentence becomes: "Rows are never deleted (DB_STANDARD §6; a `done` row is the queue's
  dedupe and the console's count; design storage-tidy-up, decision 12)."

**DB_STANDARD §10**: the first sentence becomes "`napix_responses.payload` keeps every answer verbatim, referenced
from `case_snapshots` (amended 25 Oct 2026, design storage-tidy-up), so nothing is lost."

## Services

**`services/napix_store.py`**
- `NapixRecorder.store_now(session, result) -> uuid.UUID | None`.
  - It returns None, and writes nothing, when `result` is not an `ok` JSON answer.
  - **With `session_factory`:** it opens an apart session, runs `store_response(s, result, self.job_run_id)`, commits
    and returns the id.
  - **Without one:** it runs `store_response(session, result, self.job_run_id)` in the caller's session.
  - It does not touch `pending`, so the normal flush still writes the call-log row and finds the same answer row
    (`ON CONFLICT` bumps `last_seen_at`).
  - It records `(api, params_sha256) → id` in `response_ids`, as a flush does.
- `store_response` is unchanged.

**`services/cases.py`**
- `SnapshotRef(response_id: uuid.UUID, payload_key: str | None)` (frozen dataclass).
- `snapshot_ref(recorder, result, block) -> SnapshotRef | None`. It returns None when `recorder` or `result` is None.
  - Otherwise the key is None when `block is result.data`, or the key `k` of `result.data` whose value `is` the block
    (identity, so a batch with two blocks for one CNR picks the one applied).
  - It checks `payload_sha256(block) == payload_sha256(result.data if k is None else result.data[k])`, then calls
    `recorder.store_now`. If anything fails, it returns None and the payload is kept.
- `_snapshot(session, case, source, data, ref: SnapshotRef | None = None) -> bool`.
  - **New row:** with `ref`, it writes `response_id`, `payload_key` and `payload = NULL`; without `ref`, it writes the
    payload (today's behaviour).
  - **Existing (case_id, sha) row:** it bumps `last_seen_at`. If that row has a payload and no `response_id` and a
    `ref` is given, it heals the row (decision 7).
- `apply_dossier(session, case, data, *, ref=None)` and `apply_status(session, case, block, *, ref=None)` pass `ref`
  through. `apply_dossier` no longer sets `case.raw`; `_sync_orders` no longer sets `o.raw`.
- `snapshot_block(session, snapshot) -> Any`: the rebuilt block (decision 2).

**`services/court_search.py`**: `fetch_dossier(..., recorder: NapixRecorder | None = None)`.
- After `data = await hc.case_by_cnr(cnr)`, it builds `ref = snapshot_ref(recorder, hc.last, data)` and calls
  `apply_dossier(..., ref=ref)`.
- Every caller passes its recorder:
  - the request paths (`_search_cnr`, `_search_case_number`, `_search_filing`, `fetch_court`), which have it from
    `_with_napix`;
  - the runner's dossier dispatch (`self.recorder`).

**`services/tracking.py`**: `run_status_batch(session, hc, ref, *, recorder=None)` takes `result = hc.last` after
`current_status`, and calls `apply_status(..., ref=snapshot_ref(recorder, result, block))` for each block. The runner
passes `self.recorder`.

**`services/orders.py`**
- `order_event_wanted(order_date, lane, today, max_age_days) -> bool`: `lane == request` or
  `alert_rules.is_recent(order_date, today, max_age_days)`.
- `enqueue_order_pdfs` emits `order_found` only when it is true, using `origin.lane`.
- `fetch_order_pdf(session, hc, store, ref, origin: QueueOrigin | None = None)` emits `order_stored` only when it is
  true. The runner passes the item's origin, and a missing origin counts as `daily`.
- The days come from `Settings.alert_event_max_age_days`, so the two rules cannot drift.
- Queueing, downloads and documents are unchanged.

**`services/causelists.py`**: `_entry_row` writes `raw = slim_entry_raw(e)`, a new function: the untyped fields plus
the original of any truncated typed field (decision 11). `entry_values`, the fingerprint and readers are unchanged.

**`services/storage_tidy.py`** (new), used by `aslms ops storage-tidy`:
- `report(session) -> dict`, read-only. It gives:
  - the counts of snapshots with a payload, broken down by "matchable to a stored answer" and "kept";
  - the counts of `cases.raw` and `orders.raw` values (verifiable or kept);
  - table and column sizes.
- `apply(session_factory, *, steps=("snapshots", "cases_raw", "orders_raw"), batch=5000, max_seconds=1800) -> dict`.
  Each batch selects rows `FOR UPDATE SKIP LOCKED`, updates only the verified ones, and commits.
  - **snapshots, `cnr`:** match by `payload_sha256` to answers whose `api` is the CNR path or its alternative (the
    integration's `API['cnr']` and `API['cnr_alt']` values), then `r.payload = s.payload`. The earliest
    `fetched_at` wins. Set `response_id` and clear `payload`.
  - **snapshots, `current_status`:** match the blocks of Current Status answers (`jsonb_each`) whose `cino` equals
    the case's CNR, then `value = s.payload`. The earliest answer wins. Set `response_id`, `payload_key` and clear
    `payload`.
  - **cases_raw:** NULL where a CNR answer referenced by one of the case's snapshots equals `cases.raw`.
  - **orders_raw:** NULL where an element of `interimorder` or `finalorder` (object values or array elements) of a
    CNR answer referenced by one of the case's snapshots equals `orders.raw`. The orders step runs after the
    snapshots step.
  - Rows that do not verify stay untouched and are counted as `kept`.
  - It writes one `job_runs` row (job `storage-tidy`). When it changed rows, it writes one `audit_log` row
    `system.storage_tidied` (system actor, `actor_name` "aslms ops storage-tidy") with the counts per step and the
    table sizes before and after.

**`cli/ops.py`**: `aslms ops storage-tidy [--apply] [--step snapshots|cases-raw|orders-raw|all] [--batch N]
[--max-seconds N] [--format md|json]`. A dry run (the report) is the default. Exit 0 when done; exit 3 when
`--max-seconds` stopped it with work left (run it again).

**Domain models**:
- `CaseSnapshot`: `response_id` (`uuid_fk("napix_responses.id", nullable=True, index=False)`), `payload_key`
  (`String(40)`), `payload` nullable, the two CHECKs, and `case_id` with `index=False`.
- `CaseParty.name_normalised`: `index=False`.

## API
No endpoint is added or changed, and no permission. `case_snapshots` and `napix_responses` are not exposed by any
case API (`services/case_detail.py`). The System health inspector reads `napix_responses` behind
`admin.service_health` as before. The visibility rules are unchanged.

## Jobs
No new scheduled job. `aslms ops storage-tidy --apply` is run once by the operator after the build is deployed, and
again only if a report shows matchable rows. The runbook (`docs/operations.md`) gets a section with:
- the report, then `--apply`;
- the `VACUUM (FULL, ANALYZE) case_snapshots, cases, orders` window with `api`, `worker` and `scheduler` stopped, run
  as `POSTGRES_USER`;
- the expected numbers.

## Tests
Unit (`tests/unit/test_storage_tidy_unit.py`):
- `test_snapshot_ref_whole_answer_has_no_key`: a dossier block that is `result.data` gives key None.
- `test_snapshot_ref_status_block_names_its_key_by_identity`: two blocks with equal content under `cases3` and
  `cases7` give the key of the applied object.
- `test_snapshot_ref_refuses_on_hash_mismatch_or_missing_recorder`: returns None, so the payload is kept.
- `test_order_event_wanted`: request lane always; daily, load and discovery only within the max age; future dates
  recent; an unknown date not recent.
- `test_slim_entry_raw_loses_no_parser_field`: for parsed sample entries, each `Entry` field is either a typed column
  with an equal stored value or a key of the slim `raw`. A 250-character `case_no_text` keeps its original.
- `test_every_dossier_and_status_caller_passes_the_recorder`: a source scan of `services/runner.py` and
  `services/court_search.py` call sites of `fetch_dossier` and `run_status_batch`.
- `test_no_writer_sets_cases_or_orders_raw`: a source scan of `services/`.
- `test_napix_coverage` stays green: the amended homes still exist as table.column.

Database (`tests/db/test_storage_tidy.py`, with the scripted gateway in `tests/db/conftest.py`):
- `test_dossier_fetch_keeps_one_verbatim_copy`: one `napix_responses` row. The snapshot has `payload` NULL,
  `response_id` set and `payload_key` NULL, and `snapshot_block` hashes to `payload_sha256`. `cases.raw` and every
  `orders.raw` are NULL. Every typed column and child table is filled exactly as `test_pipeline` expects. **No NAPIX
  field is lost.**
- `test_status_batch_snapshots_point_into_the_answer`: a batch answer of several CNRs. Each snapshot names the batch's
  answer and its own `cases<n>`, and the rebuilt block equals the block sent.
- `test_request_path_references_an_answer_committed_apart`: `POST /cases/search-court` by CNR through the API with the
  apart factory completes under a 10 s `statement_timeout` (no self-deadlock). The snapshot references a row that
  exists after the request.
- `test_failed_runner_item_keeps_its_answer_and_call_rows`: a dispatch that raises after `store_now`. After rollback
  and the runner's flush, the answer row and the call-log rows exist.
- `test_snapshot_without_recorder_keeps_payload`, and `test_legacy_snapshot_heals_on_next_fetch`.
- `test_stored_answer_cannot_change`: UPDATE of `payload`, `payload_sha256`, `api` or `params` raises; UPDATE of
  `last_seen_at` works; `aslms_app` cannot DELETE.
- `test_tidy_dry_run_changes_nothing`; `test_tidy_apply_is_batched_resumable_and_audited`: with batch 2 and a
  `max_seconds` stop, the second run finishes; exactly one audit row per applying run.
- `test_tidy_keeps_what_it_cannot_verify`: a snapshot whose answer is missing, a `cases.raw` that differs, and an order
  row absent from every answer are all kept. `interimorder` is tested in both object and array form.
- `test_case_history_intact_after_tidy`: for every snapshot, the sha256 of `snapshot_block` is unchanged, and the
  order by `fetched_at` and `last_seen_at` is unchanged.
- `test_order_events_live_and_request_only`: an old order on the daily lane raises no `order_found` or
  `order_stored`; a recent order raises both; an old order on the request lane raises both. Events that existed
  before are untouched (count and ids).
- `test_new_order_alert_still_raised_for_a_recent_order`: the alert scan over the event raises `new_order` as today.
- `test_new_causelist_entries_get_slim_raw`; existing rows are unchanged by a reparse.

Migration (`tests/db/test_migration_00NN.py`, marker `migration_cycle`; it runs on the test database of the run,
**never** `aslms`):
- `test_00NN_schema`: the columns, both CHECKs, the trigger, and `attcompression = 'l'` on `document_text.full_text`.
  The two indexes are gone, and `uq_case_snapshots_case_id_payload_sha256` is present.
- `test_00NN_up_down_up_restores_every_value`: seed snapshots (cnr and status), cases and orders with `raw`. Upgrade,
  tidy `--apply`, then downgrade: every `payload` is back and hash-equal, `cases.raw` and `orders.raw` are back and
  equal to the originals, and the two indexes are recreated. Upgrade again, and a second tidy changes the same rows.

## Verification
1. `ruff check` clean and `pytest -q` green, including the `migration_cycle` tests on the test database.
2. On a scratch copy of dev, never `aslms` itself: a database restored from `aslms ops backup` by `aslms ops
   restore-check`, or `createdb aslms_scratch` with `pg_restore`.
   - Run `migrate`, then `aslms ops storage-tidy`. Expected report: about 128,100 snapshots matchable and 0 kept;
     about 54,100 `cases.raw` and about 304,000 `orders.raw` verifiable. The figures grow with the load.
   - Run `--apply`, timed; minutes are expected. Then the report again: 0 snapshot payloads and 0 raw values left,
     except any reported as kept.
   - `SELECT count(*) FROM case_snapshots s LEFT JOIN napix_responses r ON r.id = s.response_id WHERE s.payload IS
     NULL AND r.id IS NULL` returns 0.
   - A sha check of 1,000 random snapshots through `snapshot_block` returns 1,000 equal.
3. Sizes on the scratch copy, before and after `VACUUM (FULL, ANALYZE) case_snapshots, cases, orders` (timed).
   Expected:
   - `case_snapshots` 238 → about 55 MB;
   - `cases` 255 → about 160 MB;
   - `orders` 197 → about 135 MB;
   - the database about 2.56 → about 2.2 GB, with the two indexes (16.5 MB) included.
4. Live check (dev worker running the new code): fetch one case through Search by CNR, then run one status batch.
   The new snapshots have `payload` NULL and a `response_id`, `cases.raw` stays NULL, and no deadlock is logged.
   Run a daily-lane order PDF of an old order: no new `order_found` or `order_stored` event. A request-lane order
   fetch writes both.
5. The owner applies to `aslms`: the `migrate` step, `aslms ops storage-tidy --apply`, then optionally the
   `VACUUM FULL` window.

**Expected savings** (dev, 25 Oct 2026):

| Item | Now | After |
|---|---|---|
| snapshot payloads | 151 MB | 0 (all 128,100 point to their answer) |
| `cases.raw` | 97 MB | 0 |
| `orders.raw` | 63 MB | 0 (only those not verified stay) |
| two indexes | 16.5 MB | 0 |
| **total** | about 330–360 MB once vacuumed (about 14% of the database) | |

Going forward:
- each new dossier version stores about 1.8 KB once instead of three times, plus about 200 bytes per order;
- each Current Status block costs about 170 bytes instead of about 650;
- each new cause-list entry is about 540 bytes smaller;
- order events drop by about 97% (in dev history they are 441,518 rows, about 107 MB plus their index share, all
  kept);
- lz4 gains no space (measured) and is CPU only, on `document_text.full_text`.

**Risks**
- **One copy means one point of failure.** This is mitigated by:
  - the frozen trigger and the RESTRICT key;
  - the never-purge rule;
  - backups (`compose.yml` keeps the backup service for the pilot);
  - the downgrade restoring every copy from the answers.
- **A request-path deadlock.** It is designed out (decision 4) and tested with a statement timeout.
- **Reading a status block reads the whole answer** (about 30 KB compressed for about 95 cases). Snapshots are not
  read in normal work today.
- **The timeline loses order lines for old orders.** The Orders tab stays complete (decision 10). If the owner later
  raises `ALERT_EVENT_MAX_AGE_DAYS`, events skipped before that are not written again.
- **`VACUUM FULL` needs a short stop.** Plain vacuum alone already stops the growth.
- **Mixed pglz and lz4 values in `full_text`** are supported since PostgreSQL 14. A `pg_restore` rewrites them as lz4.

## Open questions
The status is `awaiting-approval`: each point below has a recommended answer, and this note is written on it.
Approving the note accepts the recommendations unless the owner says otherwise.

a. **The single verbatim home.** Should it be `napix_responses`, with `case_snapshots` pointing to it, and with the
   coverage addendum and DB_STANDARD §10 amended as written under "Data"? *Recommended: yes* (decisions 1–3). It
   already holds every one of these blocks.
b. **Empty `cases.raw` and `orders.raw`** where verified inside a stored answer, keeping the columns? *Recommended:
   yes* (decision 5). That is 160 MB, nothing reads them, and the downgrade restores them.
c. **Compression.** Should it be lz4 only for `document_text.full_text`, with no `toast_tuple_target` change and no
   recompression rewrite, unlike the backlog wording? *Recommended: yes* (decision 8). Measured: lz4 makes CNR answers
   13% larger, and the toast target has no effect below 2 KB rows.
d. **Order events by the order's age, not by lane**, unlike the backlog wording. *Recommended: yes* (decision 10). All
   order-PDF rows in dev are in the daily lane. The date rule keeps every alert and cuts about 97%.
e. **`causelist_entries.raw` slimmed for new rows only**, with old rows untouched. *Recommended: yes* (decision 11).
f. **No `fetch_queue` purge now**, and the addendum aligned with schema.md's "no DELETE". *Recommended: yes*
   (decision 12). Revisit after the historical load, as a new row if wanted.
g. **The `VACUUM FULL` window on dev.** *Recommended: yes, once, after `--apply`.* It returns about 330 MB within a
   minute, while `api`, `worker` and `scheduler` are stopped.
