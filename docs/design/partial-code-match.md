# Design: Partial counsel-code match as a possible match

```
slug: partial-code-match
status: awaiting-approval
author: architect
date: 2026-10-25
approved_by:
```

## Context
Plan §4.1 and §4.2: the standing counsel code printed in the cause list's advocate column ("SC, EDU", "PP, ASSAM")
is the strongest signal. Each code is mapped to its department, every case is scored for every department, and the
department decides by claiming. Scores of 0.85 and above are strong recommendations, 0.50 to 0.85 are possible
matches, and below 0.50 there is no recommendation.

**Owner decision of 25 Oct 2026.** Departments give their counsel codes, and the system must follow them closely to
recognise their cases in cause lists. An **exact** code match stays a strong recommendation (counsel_code weight
0.95). A **partial** match must **also** be recommended, at a lower score, as a **possible match**. Case Claim shows it
to the department with the reason, and the user decides whether to claim. Nothing is ever assigned automatically. The
per-code weight override and the Notes field leave the mapping form in the UI polish item (row 153). Weights stay
global on the Scoring tab. The examples the owner accepted:

| Cause list shows | Department's code | Result |
|---|---|---|
| `SC, EDU` | `SC, EDU` | exact: strong |
| `SC, EDU, DSE` | `SC, EDU` | partial: possible match |
| `EDU` | `SC, EDU` | partial: possible match |
| `SC, HEALTH` | `SC, EDU` | no match |

**What exists** (`backend/aslms/services/matching.py`, designs `recommend-and-claim` and `ownership-refinements`):
- `normalise_counsel_code` upper-cases, collapses whitespace, puts exactly one space after each comma and none
  before, and strips trailing commas (`"sc , edu,"` → `"SC, EDU"`). Matching is exact on that form. The owner's
  decision of 13 Oct 2026 stands: a dot makes a different code, so `SC, ELEM. EDU` and `SC, ELEM. EDU.` are mapped
  separately.
- `CaseEvidence.gather` takes codes from `causelist_entries.counsel_codes` of current (not superseded) lists, most
  recent listing first, with ref `{list_date, sr_no}`, and from current `case_advocates.counsel_code`, with ref
  `{side}`.
- `RuleSet.load` puts each active code in `codes` (normalised code → one `Rule`; `counsel_codes.code` is unique) or,
  when `is_generic_state` is set (mapped to the root `GOA`), in `generic_codes`. A generic code scores nothing.
- `score_case` keeps the strongest weight within each signal kind and combines kinds by noisy-OR
  (`1 − ∏(1 − w)`). The signals go to `case_office_scores.signals`, and `apply_scores` opens, re-bands or expires
  engine recommendations. A case that has ever had a primary owner gets no engine recommendation. A department that
  dismissed or claimed a case is never re-recommended.
- Weights are **columns** of the versioned master `scoring_settings` (`weight_counsel_code` …), not a JSON object.
- Alerts are raised only for a `recommendation_made` event on a **strong** (`high`) engine recommendation of a
  pending case (`alerts.py`). The daily digest already counts a department's open **possible** (`medium`)
  recommendations (`notifications.py`).
- The unmapped-codes panel (`GET /admin/counsel-codes/unmapped`, `matching.unmapped_codes`) lists printed codes that
  no active mapping names exactly.

**What the dev data says** (read-only queries on 25 Oct 2026; current lists only): 145,374 cause-list entries, 105,694
of them with codes; 172,222 printed codes; 974 distinct raw codes (950 after normalisation); 386 distinct codes on
34,955 current `case_advocates` rows. The dev database has **no** counsel-code mappings yet and one
`scoring_settings` version (the defaults); it is at migration 0025.
- 723 normalised codes (158,682 printed codes) have two parts, almost all `SC, <office>`. 88 have one part, mostly
  designations or dot-joined forms (`DY.S.G.I.` 11,064, `SC. REVENUE` 462, `AMICUS CURIAE` 143). 139 have three or
  more parts (594 printed codes). Most of those come from a respondent marker split at its comma (`SC, GHC (R- 2,
  3)`, `GA, ASSAM(R1, 3)`), from an advocate's name (`SC, SCERT, MR. S. BORA`), or from two counsel in one string
  (`SC, HIGHER EDU, SC, COTTON UNIVERSITY`).
- First parts seen: `SC` 84,108, `PP` 38,623, `GA` 35,832, `SR. GA` 449, `ADDL. AG` 109, `AG` 61, `SR. SC` 31,
  `AMICUS CURIAE` 22, `SR. GA ADV.` 8, `SR.GA` 6, `ADDL. PP` 5, `SR. AG` 5, `ADDL AG` 3, `CGC` 3,
  `LEGAL AID COUNSEL` 2. State names as last parts: `ASSAM` 74,156, `NAGALAND` 186, `AP` 154, `MIZORAM` 153,
  `A P` 27, `MANIPUR` 8. Parts that appear in the most distinct codes: `SC` (690 codes), `ASSAM` (117), `GA` (117),
  `PP` (21), `AG` (15), `SR. GA` (13).
- Whole words inside a part are shared by different offices: `EDU` sits in `SC, EDU`, `SC, ELEM. EDU`,
  `SC, SEC. EDU.` and `SC, HIGHER EDU`, which are different directorates.
- A simulation of the rule in this note, with every non-generic printed code seen 50 times or more mapped as an exact
  code (125 codes), gives: 78,681 printed codes exact; 88,001 made only of generic parts (no match); **552 partial**
  (542 to one department, 10 to two); 4,988 with no match. Without removing respondent markers (decision 4), only 96
  are partial. With codes seen 10 times or more mapped (291 codes): 82,215 exact, 416 partial, 1,590 no match.

**Out of scope.** Word-level or prefix matching inside a part (decision 3). Reading dot-joined forms such as
`SC. REVENUE` as `SC, REVENUE` (13 Oct decision; the panel lists them, decision 16). Removing the per-code weight and
the Notes field from the form (row 153). The standing-counsel visibility basis and the inbox "State party" filter
(both stay exact, decision 15). Department discovery (row 19) searches only on exact codes.

## Decisions
1. **Code parts.** A code's parts are its comma-separated tokens after `normalise_counsel_code`, read as a set: empty
   tokens are dropped and a repeated part counts once. The comparison form (decision 4) is used for partial matching
   only. Exact matching is unchanged: the normalised printed code must equal the mapped code.
   *Alternatives:* word sets (rejected, decision 3); an ordered prefix (rejected: `EDU` in the owner's example is not
   a prefix of `SC, EDU`).
2. **The partial rule.** Take a printed code P that is not generic (decision 6) and that no active code names exactly
   (decision 7). For each active, non-generic mapped code D of a department:
   - **contained**: parts(D) ⊊ parts(P). The department's code sits inside a longer printed code, as in `SC, EDU`
     inside `SC, EDU, DSE`.
   - **contains**: parts(P) ⊊ parts(D). The printed code is part of the department's code, as in `EDU` inside
     `SC, EDU`.
   - **same parts**: parts(P) = parts(D) but the strings differ, as in `EDU, SC`, a repeated part, or a respondent
     marker removed (decision 4). This is a possible match, never strong: only the printed form itself is firm
     (open question c).
   - **The smaller set must hold at least one part that is not generic.** The smaller set is parts(D) for contained,
     parts(P) for contains, and either for same parts. So `SC` alone matches no department, and a department code
     made only of generic parts (`SC, AG`) never matches partially. It still matches exactly.
   - In every other case there is no match: `SC, HEALTH` against `SC, EDU`, or `SC, EDU, DSE` against
     `SC, EDU, HIGHER` (they overlap, but neither set holds the other).
   *Alternative:* requiring a non-generic part only for "contains", as the owner's sentence reads. Rejected because a
   department code of generic parts only would then match every longer printed code that holds it. The owner's
   purpose ("`SC` alone must NOT match every department") covers both directions.
3. **Parts are compared whole. No word-level matching.** The data shows the same word (`EDU`) in four different
   offices' codes (Context). Matching on words would put `SC, ELEM. EDU` in front of the department that maps
   `SC, EDU`. A variant such as `SC, FINANCE DEPTT.` is mapped as its own exact code (13 Oct decision).
   *Alternative:* word containment (rejected for the reason above).
4. **The comparison form removes respondent markers.** Before splitting, each parenthesised group that starts with a
   respondent number is removed, together with an unclosed group at the end of the code. The pattern is
   `\(\s*R[\s.\-]*\d[^)]*\)?`: it removes `(R-2, 3)`, `(R2, 4)`, `(R- 151, 152, 153)`, `(R 10, 11)`, `(R1-R5, R9)` and
   `(R-3 )`, but not `(A AND E)` or `(MR.H.RAHMAN, MS.J.HUDA)`. Trailing commas and spaces left over are stripped. The
   markers name respondents, not offices. They split at their own commas and would otherwise hide the office part
   (`SC, HEALTH(R-1, 2, 4)`). With removal, the simulation finds 552 partial matches instead of 96.
   *Alternative:* no removal, so the panel lists them for exact mapping. Rejected: these strings vary per case and
   cannot sensibly be mapped one by one. Dots stay significant, per the 13 Oct decision (open question a).
5. **The generic-token stop-list.** `matching.GENERIC_PARTS`, a frozenset in code chosen from the dev data above (only
   tokens seen in it, plus the owner's own examples):
   - counsel designations: `SC`, `SR. SC`, `STANDING COUNSEL`, `GA`, `SR. GA`, `SR.GA`, `SR. GA ADV.`, `PP`,
     `ADDL. PP`, `AG`, `ADDL. AG`, `ADDL AG`, `SR. AG`, `CGC`, `SR. CGC`, `DY.S.G.I.`, `AMICUS CURIAE`,
     `LEGAL AID COUNSEL`;
   - State names: `ASSAM`, `NAGALAND`, `MIZORAM`, `AP`, `A P`, `MANIPUR`.

   `AG` is on the list because the owner named it and because, alone, it denotes the Advocate General, while
   `SC, AG` is the Accountant General. `AG` alone must not reach the department mapping `SC, AG`, which still
   matches exactly. **The super admin can extend the list without a release:** every active generic State code
   (`is_generic_state`, on `GOA`) with exactly one part, such as `SR. GA ADV.`, is a generic part too. The stop-list
   affects partial matching only.
   *Alternatives:* a new `ref_*` table with a screen (rejected for Phase 1: no screen is asked for, and the
   single-part generic code already gives an editable route); guessing tokens not in the data, such as `ASG` or
   `ARUNACHAL PRADESH` (refused: never guess).
6. **Generic State codes.** A printed code that equals an active generic State code is skipped, as today, and is never
   tried for partial matches. A printed code made only of generic parts (`GA, ASSAM`, `PP, ASSAM`, `SR. GA, ASSAM`) is
   also skipped for partial matching, even before an administrator enters it as a generic code (the dev database has
   none yet). Generic codes are never partial-match targets: they are not department rules. Single-part generic
   codes extend the stop-list (decision 5).
7. **Exact wins.** When a printed code equals any active mapped code, only the exact signal is recorded for it.
   Another department whose code holds it, or is held by it, gets no partial signal from that printed code. A
   printed code that a department has mapped exactly identifies that department firmly. The partial rule exists for
   printed codes that no mapping names. *Alternative:* also giving partial signals to the others (rejected: every
   exact `SC, EDU` listing would then also put the case before the department mapping `SC, EDU, DSE`, to be
   dismissed again and again). Open question b.
8. **One code signal family per department.** When a department has an exact `counsel_code` signal on a case, its
   `counsel_code_partial` signals are dropped, both from the score and from the signal list. The two kinds come from
   the same evidence (counsel codes), so counting both by noisy-OR would double-count it (0.95 and 0.6 would give
   0.98). The score of every case with an exact match stays exactly what it is today.
9. **Several departments.** Every department with a partial match gets its own partial signal and, alone, a possible
   match. There is no tie-break and no sharing of the weight. The plan allows a case to be recommended to more than
   one department, and each decides (a claim by one closes the others' rows as `claimed_elsewhere`, per
   `ownership-refinements`). Several codes of one department that match partially give one weight for the kind (the
   strongest, all equal), with one signal per rule. `suggested_unit` follows the existing rule (strongest weight,
   then the deepest office).
10. **Score: a new signal kind `counsel_code_partial`, default weight 0.600.** This sits inside the possible band
    (0.50 ≤ 0.6 < 0.85). It combines with the other kinds by the existing noisy-OR: a partial match with a keyword
    (0.4) gives 0.760, still possible; with a name pattern (0.8) it gives 0.920, strong, because two independent
    signals agree. The per-code `counsel_codes.weight` override applies only to exact matches and is never used for
    a partial signal. The partial weight is always the global setting (the owner: weights stay global).
11. **The weight is a new column, so this needs a migration.** `scoring_settings` holds one numeric column per kind,
    with CHECKs, so the weight cannot go into a JSON object: `weight_counsel_code_partial numeric(4,3)`. It is
    nullable only for the historical versions written before it existed. Migration **0026** (the next free number
    after 0025; it takes the next free number at build time if another migration lands first). `schema.md` is
    extended first.
12. **The partial weight stays inside the possible band** (enforced by the service and by the browser checks, open
    question d): `threshold_possible ≤ counsel_code_partial < threshold_strong`, and
    `counsel_code_partial < counsel_code`. So a partial match alone is always a possible match, never strong and
    never nothing, as the owner decided, and it never outweighs an exact match. A save that would break the rule
    (for example raising the possible threshold above the partial weight) is refused with a message naming the
    partial weight. *Alternative:* a free weight (rejected: a weight of 0.9 would make a partial match strong, and
    0.4 would hide it, against the owner's decision).
13. **Reason text.** Each partial signal carries a server-written `reason` and the structured fields behind it
    (`printed`, `relation`). The Case Claim modal's "Why this is suggested" box shows the `reason` line with its
    contribution (0.600). The wordings:
    - contained: "Code SC, EDU found inside SC, EDU, DSE on the cause list of 23 Oct 2026"
    - contains: "Code EDU on the cause list of 23 Oct 2026 is part of SC, EDU"
    - same parts: "Code SC, GHC (R- 2, 3) on the cause list of 23 Oct 2026 has the same parts as SC, GHC"

    For a `case_advocates` source, "on the cause list of <date>" becomes "in the case's advocate list
    (<side> side)". The date is the list date, written as the day, the short month and the year. The printed code
    is shown in its normalised form. *Alternative:* the portal builds the sentence from the fields. Rejected: the
    same text is needed by the scores endpoint, the suggest dialog and future exports, and one server function keeps
    the wording in one place.
14. **Alerts: confirmed, no alert for a possible match.** The rule stays: a `recommendation` alert only for a strong
    engine recommendation of a pending case. A partial match alone opens a `medium` row that raises no alert. It
    appears in Case Claim (the Recommended view lists `medium` rows after `high` ones), in the department's
    possible-match count, and in the daily digest's count of possible matches waiting. When a partial match combines
    with another signal into the strong band, the existing band-change event raises the usual alert. *Alternative:* an
    alert for every possible match (rejected: the engine's `medium` rows have never alerted, and with partial codes
    they would become a stream of low-confidence alerts).
15. **Visibility does not widen.** A department sees a case with a partial match through the existing `recommended`
    basis, and only while its recommendation is open. The standing-counsel `counsel` basis and the inbox
    "State party" filter keep matching exact codes only (`visibility.codes_condition`), because a partial match is
    not firm enough to show case records to counsel. Everything is still decided in SQL on the server.
16. **The unmapped-codes panel keeps listing partly matching codes, with a note.** A printed code that only partly
    matches a mapping is still not mapped. Mapping it exactly is how a department turns a possible match into a
    strong one, and the panel is where it finds the printed forms. So it stays on the list, and each row gains
    `partial_matches`: up to 5 mapped codes it partly matches, each with its office code and relation. The list
    holds only mappings in the caller's office subtree (all of them for the super admin), the same scope as
    `GET /admin/counsel-codes`, so a department admin never learns another department's codes. The panel shows
    "Partly matches SC, EDU (EDU)". When exactly one such mapping is in scope, the panel's "Map" button pre-fills
    that office; it still sends nothing. *Alternative:* hiding partly matched codes (rejected: departments would
    never see the variants to map exactly).
17. **Engine version 2.** `ENGINE_VERSION` becomes `"2"`, so `engine_version` reads `2.<settings version>` and every
    score row says it was computed with partial matching.
18. **Rescore.** Migration 0026 inserts a new current settings version on a database that has one (Data). The
    15-minute `rescore-dirty` job sees a scoring-settings row newer than the last rescore and rescores every case.
    `aslms rescore --all` does the same at once, and the Verification runs it. On the dev database, with no mappings
    yet, the rescore changes nothing. Once departments map their codes, each mapping change triggers the same dirty
    rescore within 15 minutes (as today).
19. **Never auto-assign.** The engine still never writes `case_ownership`. A partial match only ever produces a
    `case_office_scores` row and, in the band, a `recommended` row. Every existing guard stays in force: no engine
    recommendation on a case that has ever had a primary owner, and none for a department that dismissed or claimed
    the case.

## Data
Migration **0026** `0026_partial_code_match.py` (hand-written: one column, two CHECKs and a data step).

**`schema.md`, `scoring_settings` row, replaced by:**

| `scoring_settings` (master, versioned) | id, version integer (unique), weight_counsel_code, weight_name_pattern, weight_watchlist, weight_linked_case, weight_keyword numeric(4,3) (each > 0 and ≤ 1, CHECK `ck_scoring_settings_weights`), weight_counsel_code_partial numeric(4,3) NULL (NULL only on versions written before migration 0026; CHECK `ck_scoring_settings_partial`: NULL or > 0 and ≤ 1; CHECK `ck_scoring_settings_partial_current`: NOT is_current OR weight_counsel_code_partial IS NOT NULL), threshold_strong, threshold_possible numeric(4,3) (CHECK `ck_scoring_settings_thresholds`: 0 < possible < strong ≤ 1), reason text, is_current boolean default false, valid_from timestamptz default now(), valid_to timestamptz (CHECK `ck_scoring_settings_current`: is_current = (valid_to IS NULL)), created_at, updated_at, created_by, updated_by (→ users SET NULL) | Partial unique `ix_scoring_settings_current` (is_current) WHERE is_current. A save inserts a new version and closes the previous one; never updated in place for values, never deleted. The service also requires threshold_possible ≤ weight_counsel_code_partial < threshold_strong and weight_counsel_code_partial < weight_counsel_code (design `partial-code-match`, decision 12). Version 1 (0.950, partial 0.600, 0.800, 0.750, 0.700, 0.400; 0.850, 0.500; "Plan §4.2 defaults") is inserted by `aslms seed`; an empty table means the same defaults as version 0. Migration 0026 adds the next version to a database that already has one (the partial weight 0.600 and the other values copied). |

**`schema.md`, `counsel_codes` row:** add to its notes column: "`weight` overrides exact matches only; a partial
match always uses the global `weight_counsel_code_partial` (design `partial-code-match`, decision 10). An active
generic code with a single part also counts as a generic part for partial matching (decision 5)."

**`schema.md`, `case_office_scores` row:** in the notes column, replace "kind ∈ `counsel_code`, `keyword`,
`name_pattern`, `linked_case`, `watchlist`" with "kind ∈ `counsel_code`, `counsel_code_partial`, `keyword`,
`name_pattern`, `linked_case`, `watchlist`". Then add: "a `counsel_code_partial` signal also carries `printed`
(the printed code, normalised), `relation` (`contained` / `contains` / `same_parts`) and `reason` (the sentence
shown in Case Claim), and `matched` is the department's code". Change "`1.1` at the defaults" to "`2.<version>`
from migration 0026 (`2.1` on a fresh seed)".

**Migration steps (upgrade):**
1. `ADD COLUMN weight_counsel_code_partial numeric(4,3) NULL`.
2. When a current row exists, close it (`is_current = false`, `valid_to = now()`) and insert version `n + 1`. The new
   version copies the five weights and both thresholds. Its partial weight is 0.600 when
   `threshold_possible ≤ 0.600 < threshold_strong` and `0.600 < weight_counsel_code`; otherwise it is the midpoint of
   the two thresholds rounded to 3 decimals, lowered to 0.001 below `weight_counsel_code` if needed. The reason is
   "Partial counsel-code match added (design partial-code-match), partial weight <value>", with `created_by` NULL.
   Then write one `audit_log` row `scoring_settings.update` (actor_name `migration 0026`, before and after in the
   service's `summary` shape, with `after.migration = "0026"`) and one `config_changed` event
   `{entity: "scoring_settings", id, action: "update", version}` with dedupe key `scoring_settings:<id>`, as
   `scoring_settings.update` writes them (the 0022 precedent for migration-written audit rows). An empty table gets
   nothing: the seed inserts version 1 with all six weights.
3. `ADD CONSTRAINT ck_scoring_settings_partial` and `ck_scoring_settings_partial_current`. Both hold after step 2.

**Downgrade:** drops both constraints and the column. The version inserted in step 2 stays (values are never deleted;
its other values equal the previous version's), and one audit row `scoring_settings.update` is written with
`after.migration = "0026-downgrade"`.

No new table, no `ref_*` code (signal kinds are a JSON value, not a code set), no FK, no grant change (`aslms_app`
already has SELECT/INSERT/UPDATE on `scoring_settings`). The model `ScoringSettings` gains the column and the two
`CheckConstraint`s. No NAPIX field is involved.

## Services
**`services/matching.py`**
- `ANNOTATION_RE = re.compile(r"\(\s*R[\s.\-]*\d[^)]*\)?")` and `GENERIC_PARTS: frozenset[str]` (decision 5).
- `code_parts(code: str) -> frozenset[str]`, pure. Takes a normalised code, removes `ANNOTATION_RE`, strips trailing
  `", "` and spaces, splits on `","`, strips each token, and drops empty ones.
- `partial_relation(dept_parts, printed_parts, generic) -> Literal["contained", "contains", "same_parts"] | None`,
  pure. Decision 2, with the check for a non-generic part on the smaller set. It is called only when the two
  normalised strings differ.
- `partial_reason(dept_code, printed, relation, where, ref) -> str`, pure. The sentences of decision 13. The date is
  written as `f"{d.day} {d:%b %Y}"`, which avoids the platform-specific `%-d`.
- `Rule` gains `parts: frozenset[str] = frozenset()`, filled for `counsel_code` rules from `code_parts(text)`.
- `RuleSet` gains three fields:
  - `generic_parts`: `GENERIC_PARTS` plus the parts of every active single-part generic code.
  - `partial_index: dict[str, list[Rule]]`: each non-generic part → the code rules holding it. The smaller set must
    hold a non-generic part, and that part is in both sets, so the index finds every candidate.
  - `_partial_cache: dict[str, list[tuple[Rule, str]]]`, kept per printed code for the life of the rule set. There are
    about 1,000 distinct codes, so a full rescore compares each code once.

  `RuleSet.partial_matches(printed) -> list[tuple[Rule, str]]` returns, in a stable order (department code, then
  rule text), every rule with a relation. It returns nothing when `printed` is in `codes` or `generic_codes`
  (decisions 6 and 7), or when every part of `code_parts(printed)` is generic.
- `score_case`: for each entry code and each advocate code that is neither generic nor exact, it adds one
  `counsel_code_partial` hit per match. The weight is `settings.weights["counsel_code_partial"]`, never the rule's
  override. The dedupe key stays `(kind, rule.id, rule.text, department, where)`, so the most recent listing gives
  the signal. The signal is `{kind: "counsel_code_partial", rule_id, rule_office_code, weight, matched: <department
  code>, printed, relation, where, ref, reason}`. Before combining, a department with any `counsel_code` hit loses its
  `counsel_code_partial` hits (decision 8). Everything else (noisy-OR, rounding, `suggested_unit`) is unchanged.
- `ENGINE_VERSION = "2"`. `apply_scores`, `score_cases`, `rescore_all` and `rescore_if_dirty` are unchanged.
- `unmapped_codes(session, *, limit=200, scope=None)`. The new `scope` is a predicate on an office id; None means the
  super admin, who sees everything. Each `UnmappedCode` gains `partial_matches: list[dict]`: up to 5
  `{code, office_code, relation}` entries from `RuleSet.partial_matches`, keeping only rules whose office is in
  scope. Which codes are listed, and their order, does not change.
- The engine writes no audit rows and its actor stays `matching` (as today). The `recommendation_made` event carries
  the band, as today.

**`services/scoring_settings.py`**
- `KINDS = ("counsel_code", "counsel_code_partial", "name_pattern", "watchlist", "linked_case", "keyword")`.
  `DEFAULTS.weights["counsel_code_partial"] = 0.600`.
- `from_row` leaves out a NULL weight (historical versions), so `Settings.weights` of such a row has no
  `counsel_code_partial`. The current row always has it (CHECK).
- `validate` adds decision 12 after the range checks, and each raises `SettingsError` (HTTP 400):
  - "the partial code weight must be at least the possible threshold and below the strong threshold";
  - "the partial code weight must be below the counsel code weight".
- `_insert` and `seed_default` write the sixth column. `update` keeps its audit row `scoring_settings.update` and its
  `config_changed` event; `summary` now carries six weights.

**`services/matching_rules.py`:** `effective_weight` is unchanged (exact matches only). No other change.

## API
| Method and path | Permission | Change |
|---|---|---|
| `GET /admin/scoring-settings` | `admin.scoring`, `admin.counsel_codes` or `admin.keywords` (unchanged) | `weights` gains `counsel_code_partial`. |
| `PUT /admin/scoring-settings` | `admin.scoring` (unchanged) | `ScoringWeightsIn` gains `counsel_code_partial: float` (`gt=0, le=1`), required. 400 with the decision 12 messages; 409 for a stale `expected_version` (unchanged). The rescore is dispatched after the commit (unchanged). |
| `GET /admin/scoring-settings/history` | `admin.scoring` (unchanged) | Each version's `weights` has `counsel_code_partial` from version 2 on (absent before). |
| `GET /admin/counsel-codes/unmapped` | `admin.counsel_codes` (unchanged) | `UnmappedCodeOut` gains `partial_matches: list[{code: str, office_code: str, relation: "contained" \| "contains" \| "same_parts"}]`, holding only mappings in the caller's office subtree (`access.in_scope`; all of them for the super admin). |
| `GET /inbox/recommended` | `cases.claim` for one's own department, `cases.view_all` for another (unchanged) | `signals` may hold `counsel_code_partial` entries (shape in Services). Rows are still listed `high` first. |
| `GET /admin/matching/cases/{ref}/scores` | `cases.view_all` (unchanged) | Same signal shape. |

There is no new endpoint, and no visibility rule changes (decision 15). The OpenAPI types in
`frontend/src/lib/api/schema.d.ts` are regenerated.

**Portal (frontend):**
- `lib/mapping.ts`: `WEIGHT_KINDS` gains `"counsel_code_partial"` after `"counsel_code"`, and `scoringErrors` adds
  the decision 12 checks on the partial field. `messages.ts` gets the label "Partial counsel code" and the hint "A
  department's code found inside a longer printed code, or a printed code that is part of the department's code.
  Stays in the possible band and below the counsel code weight." The Scoring tab renders the sixth weight from the
  list, and its history shows "—" for versions without it.
- `lib/signals.ts`: label `counsel_code_partial: "Partial code"`. `signalText` returns the signal's `reason` when it
  has one, otherwise "Partial code: <matched> in <printed>".
- `components/admin/mapping/CounselCodes.tsx`: the unmapped panel's line "Partly matches <code> (<office>)", and the
  "Map" pre-fill (decision 16). This file is also touched by row 153, so build after row 153 merges or rebase on it.
- uicheck and vitest fixtures (`claimFixtures.ts`, `mapping.test.tsx`) gain the sixth weight and one partial signal.

## Jobs
No new job. The existing `rescore-dirty` (every 15 minutes) picks up the settings version inserted by migration 0026
and any later mapping or weight change. `aslms rescore --all` is the manual route (decision 18). A full pass over the
held cases writes one `job_runs` row `rescore` with `settings_version` set to the new version.

## Tests
**Unit (`tests/unit/test_partial_code_match.py`, pure, no database):**
- `test_code_parts_normalised_and_set`: `"sc , edu,"` → `{SC, EDU}`; a repeated part counts once; empty tokens
  dropped.
- `test_code_parts_removes_respondent_markers`: `SC, GHC (R- 2, 3)`, `SC, HEALTH(R-1, 2, 4)`, `SC, F.T (R2TO4, 7)`
  and an unclosed `SC, BTC, (R- 3, 4&5` lose the marker; `SC, AG (A AND E)` and
  `SC, FINANCE(MR.H.RAHMAN, MS.J.HUDA)` keep their groups.
- `test_owner_examples` (parametrised over the four rows of the owner's table): `SC, EDU` → exact counsel_code
  0.950, band `high`; `SC, EDU, DSE` → `counsel_code_partial` 0.600, band `medium`, relation `contained`; `EDU` →
  0.600, `medium`, relation `contains`; `SC, HEALTH` → no score for the department.
- `test_same_parts_is_partial_not_exact`: `EDU, SC` and `SC, GHC (R- 2, 3)` against `SC, GHC` → relation
  `same_parts`, 0.600.
- `test_overlap_without_subset_is_no_match`: `SC, EDU, DSE` against `SC, EDU, HIGHER` → nothing.
- `test_whole_parts_only`: `SC, ELEM. EDU` and `SC, HIGHER EDU` against `SC, EDU` → nothing; `SC, SEC. EDU`
  against `SC, SEC. EDU.` → nothing (a dot makes a different code).
- `test_generic_parts_stop_list`: each `GENERIC_PARTS` token alone (`SC`, `GA`, `AG`, `ASSAM` …) matches no
  department; `SC, ASSAM` matches nothing although `SC, SCERT, ASSAM` is mapped; `AG` alone does not reach `SC, AG`;
  a department code `SC, AG` never matches partially but still matches exactly.
- `test_single_part_generic_code_extends_stop_list`: with an active generic code `SR. GA ADV.`, that token alone no
  longer matches a department code holding it.
- `test_generic_state_code_skips_partial`: a printed code equal to a generic code, or made only of generic parts
  (`GA, ASSAM`, `PP, ASSAM`, `SR. GA, ASSAM`), gives no partial signal.
- `test_exact_wins_over_partial_for_others`: printed `SC, EDU` mapped exactly to department A; department B's
  `SC, EDU, DSE` gets nothing from it.
- `test_exact_and_partial_same_department_counts_once`: entry `SC, EDU` (exact) and advocate code `EDU` (partial)
  for the same department → score 0.950 and no partial signal in the list.
- `test_several_departments_each_possible`: `SC, HIGHER EDU, SC, COTTON UNIVERSITY` with A = `SC, HIGHER EDU` and
  B = `SC, COTTON UNIVERSITY` → both 0.600 `medium`; `EDU` against A = `SC, EDU` and B = `SC, EDU, DSE` → both.
- `test_partial_combines_by_noisy_or`: partial with a keyword (0.4) → 0.760 `medium`; with a name pattern (0.8) →
  0.920 `high`.
- `test_partial_ignores_rule_override`: a code rule with override 0.99 matched partially scores the global 0.600.
- `test_reason_texts`: the three sentences of decision 13 for a cause-list ref of 23 Oct 2026, the advocate-list
  form with a side, and the `printed`, `relation` and `matched` fields.
- `test_partial_index_finds_all_candidates`: a property-style check over random part sets: the index result equals a
  brute-force scan of every rule.
- `test_engine_version_two`: `engine_version(settings)` = `"2.<version>"`.

**Database (`tests/db/`):**
- `test_matching.py::test_partial_match_writes_medium_recommendation_never_ownership`: a scripted case listed with
  `SC, EDU, DSE` gets a `case_office_scores` row with the partial signal and an engine `recommended` / `medium` row.
  No `case_ownership` row and no `audit_log` row are written.
- `test_matching.py::test_partial_match_respects_claimed_and_dismissed`: a case ever owned gets no new partial
  recommendation; a department that dismissed the case gets none.
- `test_matching.py::test_rescore_all_applies_partial_after_settings_version`: after the migration's settings
  version, `rescore_all` writes the partial rows and a `job_runs` `rescore` with the new `settings_version`.
  `rescore_if_dirty` runs once, then returns None.
- `test_alerts_generate.py::test_possible_match_raises_no_alert`: the `recommendation_made` event of a partial-only `medium`
  row raises no alert. A partial match plus a name pattern (`high`) raises one. The digest's possible-match count
  includes the partial row.
- `test_scoring_settings.py::test_partial_weight_saved_versioned_audited`: a save with `counsel_code_partial` 0.65
  inserts a version, audits `scoring_settings.update` with six weights, and emits `config_changed`.
- `test_scoring_settings.py::test_partial_weight_band_rules`: refusals for partial 0.45 (below possible 0.5), 0.85
  (equal to strong), 0.96 (above counsel_code), and for raising `threshold_possible` to 0.7 while partial is 0.6.
  Each gives a 400 message naming the partial weight and writes no version.
- `test_scoring_settings.py::test_history_shows_absent_partial_for_old_versions`: version 1 written without the
  column reads without the key.
- `test_matching_rules_admin.py::test_unmapped_lists_partly_matching_with_scope`: `SC, EDU, DSE` stays listed with
  `partial_matches` `[{code: "SC, EDU", office_code, relation: "contained"}]` for the super admin and for EDU's
  admin, and with `[]` for another department's admin.
- `test_migration_0026.py`: the column and both CHECKs exist. On a database with version 1, the upgrade closes it
  and inserts version 2 with partial 0.600 and the other values copied, plus one audit row with
  `after.migration = "0026"` and one `config_changed` event. With bands set so that 0.600 is outside them, it writes
  the midpoint. An empty table gets no row. The downgrade drops the column and constraints, keeps version 2, and
  writes the downgrade audit row. `ck_scoring_settings_partial_current` refuses a current row with NULL.
- `test_migrations.py`: the model and the migrated schema still agree (autogenerate check).

**API (`tests/db/`, through the app as the existing `test_api_*.py` files do):**
- `test_api_matching.py` (new): `PUT /admin/scoring-settings` without `counsel_code_partial` → 422; with an
  out-of-band value → 400; with `admin.counsel_codes` only → 403. `GET /admin/counsel-codes/unmapped` returns
  `partial_matches`, scoped.
- `test_api_inbox.py`: `GET /inbox/recommended` returns the partial signal with its `reason`.

**Frontend (vitest):**
- `signals.test.ts`: a partial signal shows its `reason`; a partial signal without one falls back to the
  "Partial code" text.
- `claim.test.tsx`: the Why box lists the partial line with 0.600, and the meter reads the score.
- `mapping.test.tsx`: the Scoring tab shows six weights, the band checks on the partial field, "—" in history for
  version 1, the unmapped row's "Partly matches" line, and the single-match "Map" pre-fill.

## Verification
1. `ruff check`, `pytest -q` and `npm test` all green, including the new test files.
2. Run `docker compose --profile ops run --rm migrate`. Then, read-only:
   `SELECT version, weight_counsel_code_partial, is_current, reason FROM scoring_settings ORDER BY version` →
   version 1 (NULL, false) and version 2 (0.600, true). `audit_log` has one `scoring_settings.update` with
   `after->>'migration' = '0026'`.
3. Run `docker compose exec api aslms rescore --all`. It prints counters with `settings_version: 2`. The dev database
   has no mappings, so `scores` and `recommended_new` are 0, and the `job_runs` row is `succeeded`. Within 15 minutes
   no second dirty rescore runs (`rescore_if_dirty` returns None).
4. `GET /admin/scoring-settings` as the super admin returns six weights with `counsel_code_partial: 0.6` and
   `engine_version: "2.2"`.
5. Owner's browser check at http://localhost:3000 (375, 768 and 1280 px), as the super admin:
   - Department mapping → Scoring shows "Partial counsel code 0.600". Saving 0.9 is refused with the band message.
     Saving 0.65 with a reason makes a version 3, shown in history.
   - On a test department, map `SC, EDU` and wait for the rescore (or run step 3). A held case listed with
     `SC, EDU, DSE` (or another longer form of a mapped code) appears in that department's Case Claim as a possible
     match. The Why box reads "Code SC, EDU found inside … on the cause list of <date>" with 0.600. No alert is
     raised. Claiming works as for any recommendation.
   - The unmapped panel lists the longer code with "Partly matches SC, EDU".
   - Deactivate the test mapping afterwards (audited; scores clear at the next rescore).
6. `uicheck` (`docker compose --profile uicheck run --rm uicheck`) shows no new finding on the mapping and Case Claim
   screens.

## Open questions
The status is `awaiting-approval`: each point below has a recommended answer, and this note is written on it.
Approving the note accepts the recommendations unless the owner says otherwise.

a. **Respondent markers.** Should the parenthesised respondent numbers (`(R-2, 3)`, `(R1, 3)`) be removed before
   comparing parts? *Recommended: yes, for partial matching only* (decision 4). They name respondents, not offices.
   In the dev data, removing them raises partial matches from 96 to 552 printed codes. Exact matching and the 13 Oct
   rule that a dot makes a different code are unchanged.
b. **Exact wins.** When the printed code is exactly one department's mapped code, should other departments whose
   codes overlap it also get a possible match? *Recommended: no* (decision 7). An exact mapping is a firm
   identification, and the partial rule serves printed codes that no mapping names.
c. **Same parts in another form** (`EDU, SC`, a repeated part, or a respondent marker removed, against `SC, EDU`).
   Strong or possible? *Recommended: possible* (decision 2). Only the printed form equal to the mapped code is
   strong, so the department can map the variant to make it strong.
d. **Band lock for the partial weight.** Should the Scoring tab refuse a partial weight outside
   `possible ≤ w < strong`, or one at or above the counsel code weight? *Recommended: yes* (decision 12). Otherwise a
   setting could make a partial match strong or hide it, against the decision of 25 Oct.
e. **The stop-list.** These tokens, taken from the dev data, count as generic for partial matching:
   `SC, SR. SC, STANDING COUNSEL, GA, SR. GA, SR.GA, SR. GA ADV., PP, ADDL. PP, AG, ADDL. AG, ADDL AG, SR. AG, CGC,
   SR. CGC, DY.S.G.I., AMICUS CURIAE, LEGAL AID COUNSEL, ASSAM, NAGALAND, MIZORAM, AP, A P, MANIPUR`. The super admin
   adds more by entering a single-part generic State code. *Recommended: accept as listed* (decision 5), including
   `AG`, which alone denotes the Advocate General and must not reach the department mapping `SC, AG` (the
   Accountant General).
