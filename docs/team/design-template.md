# Design: <title>

```
slug: <slug>
status: draft | awaiting-approval | blocked | approved | built
author: architect
date: YYYY-MM-DD
approved_by: <owner e-mail or name> on YYYY-MM-DD
```

## Context
Why this item exists (the plan section, the backlog line, what the user needs), what is in place already,
what this does not cover.

## Decisions
Numbered, each with the alternatives considered in one line and the reason. Anything that deviates from the
plan is marked **deviation** and flagged for the owner.

## Data
Tables and columns to add or change, written as the paragraph that will go into `docs/schema/schema.md`
(table class, keys, constraints, FK behaviour, audit columns). Reference codes to add to `ref_*` sets.
Migration number.

## Services
Modules and functions (`backend/aslms/services/...`), their inputs, rules enforced, audit and events written.

## API
Endpoints with method, path, function required (`Permission`), request and response shapes, visibility rule.

## Jobs
Scheduled or queued work, if any (kind, ref format, priority, schedule).

## Tests
The tests that must exist (unit and database), named by what they prove.

## Verification
How the integrator proves the feature works end to end (commands, expected numbers).

## Open questions
Questions only the owner can answer. A note with an open question is `blocked`, not `awaiting-approval`.
