---
name: security-audit
description: Have the security-auditor agent audit the whole ASLMS application for vulnerabilities and write a findings report under docs/audits/.
---

Launch the `security-auditor` agent (Agent tool, `subagent_type: "security-auditor"`, `isolation: "worktree"`,
in the background) on the current `main`. The argument, if any, narrows the scope (for example "uploads" or
"the backend-for-frontend"); with none, audit everything its definition lists. Give it today's date and the
path of the latest earlier audit in `docs/audits/`, so it can say which findings are fixed or still open.

When it returns, put its report on `main` (`docs/audits/<date>-security-audit.md`, committed alone with the
attribution footer) and relay it to the owner in plain words: the overall posture, every Critical and High
finding (what an attacker could do, and the fix), and the counts by severity. Offer to turn the findings into
backlog rows. Change no application code.
