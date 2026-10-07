# custody-workflow — report (7 Oct 2026)

Merged to `main` as squash commit 7b46e7d; tag `feature/custody-workflow-done`. Design note: `docs/design/custody-workflow.md` (approved).

## What changed
- Migration `0009_workflow` (request tables dropped; custody and custody_history extended with remark, holder designation and membership snapshot; case stages; draft notes, note attachments and per-note visibility; new pending-action values).
- Services: `custody.py` (send, eOffice chain, recall, exit legs), `notes.py` (append-only notes, drafts, supersedes chains), `stages.py`, `attachments.py`, `workflow_common.py`, `workflow_codes.py`; changes to `visibility.py` (holder access), `alerts.py`, `alert_rules.py`, `recipients.py`, `documents.py`, `case_detail.py`, `memberships.py`, `ownership.py`, `access_seed.py`, `seed.py`.
- API: new router `aslms/api/routers/workflow.py` (custody, stages, notes, drafts, attachments), schemas, `documents.py` changes.
- Docs: `schema.md`, decisions log, design note deviations, backlog. 58 files, +6286 / -401.
- Tests added: custody send and recall, holder access, notes, drafts, note visibility, attachments, stages, workflow alerts, API workflow, migration 0009, workflow rules.

## Gates
- `ruff check .`: All checks passed!
- `pytest -q`: 548 passed, 37 warnings in 351.83s
- `docker compose build`: succeeded (api, worker, scheduler, init built)
- `git status`: clean; design note status `approved`; decisions-log entry and backlog row present.

## Review findings (all advisory) and closure
1. Note attachments are checked only by the document rule, so the two note switches (`notes.view_private_office`, `notes.view_counsel_shared`) are not applied to attachments. Follows decision 18 as written; not fixed here. Follow-up row 32.
2. The 0009 downgrade guard does not protect `custody_history.remark`, `holder_designation`, `holder_membership_id` (the exit remark exists only there). Not fixed; the migration is applied, so any change needs a new migration or a guard in a later one. Follow-up row 32.
3. Several drafts may correct the same note; finalisation chains them silently (audit row only). Not fixed. Follow-up row 32.

## Deviations
Those recorded in the design note (deviations written back in commit e48ebe0), including the exemption of `reassigned_on_exit` legs from the downgrade guard.

## Follow-up rows
Row 32 `custody-hardening`: the three advisories above.

## Load status (`aslms queue-status`)
causelist_day: done 18, pending 606, skipped 18. dossier: done 10273, failed 80, pending 555, skipped 17. masters: done 1. order_pdf: pending 84366. status_batch: done 2, pending 10.
