---
name: team-cycle
description: Run one full team cycle on the ASLMS backlog — pick the next item (or the slug given), design, wait for approval, build, test, review, document, merge — using the team-cycle workflow. The owner's standing opt-in to multi-agent orchestration for this project.
disable-model-invocation: true
---

Run one cycle of the ASLMS agent team as described in `docs/team/README.md`.

1. Read `docs/backlog.md`. If an argument was given, it is the slug to work on; otherwise the target is the
   first row whose status is `approved`, `building` or `review` (work in progress), else the first `todo`.
   If the first unfinished row is `awaiting-approval` or `blocked`, do not start anything: report which note
   waits for the owner (`docs/design/<slug>.md`) and stop.
2. Call the **Workflow** tool with `name: "team-cycle"` and `args: {"slug": "<slug>", "today": "<YYYY-MM-DD>"}`
   (add `"dryRun": true` when the user wrote `--dry-run`: the cycle then stops after the design). The owner has
   opted into this orchestration by invoking this command.
3. When the workflow returns, read its result and report in a few lines: the phase reached, the design
   status, commits and branch, test summary, review findings and how they were closed, the report path, and
   what the owner must do next (approve a note, answer a question, or nothing).

Never set `NAPIX_ENABLED`, never touch `.env`, never run `git push`.
