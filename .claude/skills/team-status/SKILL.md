---
name: team-status
description: Show where the ASLMS team stands — backlog by status, design notes waiting for approval or blocked, feature branches, the latest cycle reports, and the data-load progress.
---

Gather and show, in one compact message:

1. `docs/backlog.md`: a count per status and the first rows that are `awaiting-approval`, `blocked`,
   `approved`, `building` or `review`, with their design-note paths.
2. For each `blocked` note, its "Open questions" section verbatim.
3. `git branch --list "feature/*"` and `git log --oneline -5 main`.
4. The two newest files in `docs/reports/` (title line and the merged commit).
5. Load progress: `cd backend && .venv/Scripts/aslms queue-status` (skip with a note if the database is down),
   plus `docker compose ps --format "{{.Name}} {{.Status}}"`.
6. The remote and CI (design github-and-ci), when `git remote get-url origin` succeeds: how far `main` is ahead
   of `origin/main` (`git rev-list --count origin/main..main`), and the last three CI runs on `main`
   (`gh run list --branch main --limit 3`, skipped with a note when `gh` is missing or not signed in).
7. What the owner must do next, if anything (approve a note, answer a question, push, fix a red CI run).

Read-only: change nothing.
