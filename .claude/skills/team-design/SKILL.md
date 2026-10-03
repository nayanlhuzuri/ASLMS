---
name: team-design
description: Have the architect write or refresh the design note for one ASLMS backlog item (docs/design/<slug>.md) without building anything.
disable-model-invocation: true
---

Launch the `architect` agent (Agent tool, `subagent_type: "architect"`) for the slug given as the argument
(or the first `todo` row of `docs/backlog.md` when none is given), with this brief:

"Design the backlog item `<slug>` (`<title>` from docs/backlog.md). Write `docs/design/<slug>.md` from
`docs/team/design-template.md`; set the backlog row's status and design column. Status `awaiting-approval`
when complete, `blocked` with the questions when a business rule or API field is missing."

When it returns, show the owner: the note path, its status, the numbered decisions, and the open questions.
Tell them to run `/team-approve <slug>` when they agree, or to edit the note and run `/team-design <slug>`
again.
