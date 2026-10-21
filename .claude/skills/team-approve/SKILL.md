---
name: team-approve
description: Record the owner's approval of a design note so the team may build it — sets status approved in docs/design/<slug>.md and docs/backlog.md and logs the approval.
disable-model-invocation: true
---

The argument is the slug. The person running this command is the owner approving the design.

1. Read `docs/design/<slug>.md`. If its status is `blocked`, do not approve: show the open questions and ask
   the owner to answer them in the note first (or answer in chat, then update the note's "Decisions" and
   "Open questions" sections and continue).
2. Set the note's status line to `approved`, and replace the existing `approved_by:` line (never add a second
   one) with `approved_by: <owner> on <today>`.
3. In `docs/backlog.md`, set the row's status to `approved`.
4. Append to `docs/claude_ASLMS_design_decisions.md` a short dated line under a section
   `## Design approvals` (create it at the end if absent): `- <date> — <slug>: approved by the owner
   (docs/design/<slug>.md)`.
5. Commit the three files on `main` with the message `Approve design: <slug>` and the footer
   `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
6. Tell the owner the next `/team-cycle` will build it.
