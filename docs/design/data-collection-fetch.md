# Design: Data Collection redesign, round 3 — Collect Now carried out at once

```
slug: data-collection-fetch
status: approved
author: architect
date: 2026-10-26
approved_by: owner on 2026-10-26, as round 3 of the revised data-collection-redesign
```

This is a pointer note. The whole design is **[data-collection-redesign.md](data-collection-redesign.md)**. The owner
reopened it on 26 Oct 2026 for four tabs and immediate manual requests (its history section); round 3 is re-approved
with it. This cycle (row 174, branch `feature/data-collection-fetch`) builds **decisions 22-33** of that note, and only
those, under its rules, API, tests and verification. It builds after round 2 (row 173) has merged.

- Build from those decisions and the API, Services, Tests and Verification lines marked for round 3.
- Record any deviation of this round in a "Deviations, round 3" section of **this** note.
- The first version of this round (day and list requests at priority 30 in the normal bands, audit actions
  `data_load.day_details_requested` / `data_load.list_details_requested`) is superseded by the "now" priorities,
  "use everything" with Stop, and `data_load.collect_requested` / `data_load.collect_stopped`.
- Round 4 (Update From the Court on the case, decisions 50-56) uses this round's engine and becomes a new row at
  approval.

## Deviations, round 3
