---
name: team-review
description: Have the reviewer agent review the current feature branch against the ASLMS rules, the database standard, the design note and security, and report blocking and advisory findings.
---

Launch the `reviewer` agent (Agent tool, `subagent_type: "reviewer"`) with the current branch name
(`git branch --show-current`) and the slug it implies (`feature/<slug>`), asking for findings as described in
its definition. Relay the findings to the owner grouped by severity, each with file:line and the failure
scenario, and the reviewer's merge verdict. Change nothing.
