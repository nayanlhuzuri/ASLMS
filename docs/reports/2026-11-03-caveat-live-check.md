# Report: Caveat live check (row 223, `caveat-live-check`)

Run 3 Nov 2026 on branch `check/caveat-live`, beside the build cycle, with the court-data switch on for each single
run only. A live check, not a build: no schema change, no application change.

## How it was run
- Probe `backend/tools/caveat_probe.py`: one call per run through `NapixClient.call` (the integration layer), with the
  client's automatic retries off, every attempt written to `napix_call_log` (and each decrypted JSON answer to
  `napix_responses`) by `NapixRecorder`, also on failure. Run in one-off containers of the api image
  (`docker compose run --rm --no-deps`); no stack service was started, stopped or recreated.
- Parameters exactly as the High Court Open API Specification v1.0, section 8:
  - Caveat Search by Name, GET `hc-caveat-name-api/caveatname`: `est_code|caveat_party_name|search_type` (8.1.4).
  - Caveat Details (the spec calls it Caveat History), GET `hc-caveat-details-api/caveatdetails`:
    `est_code|caveat_code` (8.2.4).
- All at `GAHC01` (Principal Seat). Caveat codes used in Details came from the search answers.

## Calls made: 9 of the 10 allowed
From `napix_call_log` (`api LIKE 'hc-caveat-%'`: 9 rows, 10:28:21 to 10:30:41 UTC). No token renewal was recorded.

| # | API | Input | Result | `X-RateLimit-Remaining` |
|---|---|---|---|---|
| 1 | Search | `STATE OF ASSAM`, `A` | 628 RECORD_NOT_FOUND | 98 |
| 2 | Search | `ASSAM`, `A` | 32 caveats, filed 19 Aug to 15 Oct 2026, 6 with a matched case | 97 |
| 3 | Details | `117800009342026` (from call 2) | full record, matched to `WA/326/2026` | 96 |
| 4 | Details | `117800010932026` (from call 2) | full record, the State as caveatee, no match | 95 |
| 5 | Search | `EDIFICE` (a word found only in a caveatee in call 2), `A` | 628 | 94 |
| 6 | Search | `COMMISSIONER AND SECRETARY`, `A` | 11 caveats, filed 1 to 9 Oct 2026, the Government as caveator | 93 |
| 7 | Search | `DEPUTY COMMISSIONER`, `A` | 628 | 92 |
| 8 | Search | `ASSAM`, `search_type` left out (deliberate bad input) | 620 INVALID_SEARCH_TYPE | 91 |
| 9 | Search | `ASSAM`, `S` | the same 32 caveats as call 2 | 90 |

`X-RateLimit-Limit` was 1000 on every answer and the remaining count fell by exactly one per call. All JSON answers
passed the `response_token` check. A further database look-up (no court call) found that ASLMS already holds all
six matched cases.

Samples (decrypted, no credentials) in `docs/specs/samples/caveat/`: `caveat_name_2026-11-03.json` (call 2),
`caveat_name_2026-11-03-b.json` (call 6), `caveat_details_2026-11-03.json` (call 3),
`caveat_details_2026-11-03-b.json` (call 4). They sit in a subfolder because `aslms napix-fields` and two unit tests
(`test_napix_inspect`, `test_system_health`) read every top-level sample and expect it to belong to a known API with
a schema home. Caveat fields have no schema home yet, so the field inventory was not regenerated.

## What a caveat carries
**Search answer**, `caveat.caveat{n}`:
- `caveat_no` (e.g. `934`), `caveat_year`, `caveat_filing_date`;
- `caveator_caveatee_details`: one text, `CAVEATOR VS CAVEATEE`
  (e.g. `ASSAM INDUSTRIAL DEVELOPMENT CORPORATION LIMITED RIPUNJOY CHOUDHURY VS EDIFICE ENGINEERING`);
- `matched_case_no`: `""` until the case the caveator expects is filed, then its case number (e.g. `WA/326/2026`);
- `caveat_code`: 15 digits, the key for Details.

**Details answer**:
- `caveat_details`: `caveat_no` (zero-padded `0000934`), `caveat_year`, `cnr_no`, `subject`, `caveat_filing_date`,
  `time_of_filing`, `matched_case_no` (only when there is a match);
- `caveator_details`: `caveator_name`, `caveator_add`;
- `caveatee_details`: `caveatee_name`, `caveatee_add`.

What each item covers:
- **Caveator and caveatee**: the names, with addresses empty in both samples. Each sample had one party a side, and the
  spec's `extra_party_caveator` and `extra_party_caveatee` blocks did not appear.
- **Subject and lower court**: the court does not send lower-court details as separate fields. `subject` is free text
  naming the order the caveat is about, e.g. `JUDGEMENT AND ORDER DATED 25.08.2026 PASSED IN WP(C) NO. 5859/2025 …`
  or `ORDER DATED 14.09.2026 IN WP(C) 704/2025 …`. In both samples that order was the High Court's own.
- **Dates**: the filing date, plus the filing time in Details.
- **Linked case**: `matched_case_no`, as a case number only, not a CNR.

## Differences from the specification
1. The request string in 8.1.4 prints its last item as a bare `search_type`. The server takes `search_type=A` (or
   `S`) like every other pair, and answers 620 when it is left out.
2. **Only the caveator's name is searched.** The spec says "name of the party" and "Caveator OR Caveatee". In practice
   `EDIFICE`, a caveatee in call 2's answer, gave 628, and so did `STATE OF ASSAM`, the caveatee of caveat
   `117800010932026`. A phrase of several words matches anywhere inside the caveator's name.
3. `A` (anywhere) and `S` (starting with) gave identical answers for `ASSAM`. Every match had `ASSAM` at the start of
   a word, so whether `S` differs for text in the middle of a word is not settled.
4. Details `cnr_no` is **the caveat's own filing reference** (`GAHC01-C00936-2026` for caveat 934), not the matched
   case's CNR as the spec's description says. The matched case's CNR was `GAHC010185652026`.
5. Details leaves the `matched_case_no` key out when there is no match. The search sends `""` in that case.
6. The spec marks names as "masked". No masking was seen in these answers.
7. Codes 619, 620 and 623 are not named in the client's `NAPIX_STATUS` table. Call 8 was logged as
   `NAPIX 620 UNKNOWN` with the decrypted body `{'status_code': '620', 'status': 'INVALID_SEARCH_TYPE'}`. Adding the
   names is a one-line change for a later build. Nothing was changed here.
8. Not in the spec: every answer held only caveats filed in the last 11 weeks (19 Aug to 15 Oct 2026). Caveat numbers 1
   to 903 of 2026 never appeared, even for a word as broad as `ASSAM`. A caveat lapses after 90 days (CPC s.148A),
   so the court probably serves live caveats only. This fits the evidence but is not proven.

## Recommendation: caveat alerts for departments
**Worth a small design, but not urgent. Place it after the approved queue.**

The check showed four things:
- **The search can only find caveats a department lodged itself**, because only caveator names are searched. The
  Government does lodge caveats: 11 in nine days as "THE COMMISSIONER AND SECRETARY TO THE GOVT. OF ASSAM", and
  others from State corporations and boards. The department already knows about these, so the new information is
  `matched_case_no`. It changes from empty to a case number when the expected case is filed against the department,
  which tells the department early that the case is in court.
- **A caveat lodged against the Government cannot be found by name.** The search does not match caveatee names. An
  example is the tea company's caveat against "THE STATE OF ASSAM", which signals that the State lost and an appeal
  may be due. That caveat appeared in our answers only because the caveator's name also contained "ASSAM".
- **Matching a caveat to a department is unreliable from the name alone.** The caveator is often a designation such
  as "Commissioner and Secretary to the Govt. of Assam" with no department named. Telling which department it is
  needs the Details `subject` or the matched case, and the alert should feed the recommend-and-claim flow as a
  recommendation, never as an assignment.
- **The lead time over what ASLMS already does is small.** All six matched cases were already held, found through
  the cause lists and the load. The caveat adds the days between filing and first listing, and the `subject` text.

**Cost of checking daily is negligible.**
- About 5 to 15 name searches a day, one per caveator term: for example `ASSAM`, `GOVT`, `COMMISSIONER AND SECRETARY`,
  `DIRECTOR`, `SUPERINTENDENT OF POLICE`, plus department-specific names.
- Each search lists only live caveats and already carries `matched_case_no`, so a newly filed case shows up without
  extra calls.
- One Details call per new caveat. The court's numbering suggests about 5 caveats a day for all parties together;
  the Government's share is smaller.
- So about 10 to 20 calls a day in all, under 0.1 % of the 24,000-a-day High Court allowance.
- A matched case is turned into a CNR with one existing Search by Case Number call, then handled by the existing
  pipeline.

## Needs the owner's decision
1. Whether caveat alerts are worth a design at all, given the limits above (caveator-only search and small lead
   time). If yes, it needs a backlog row placed in the queue.
2. If a design goes ahead: the caveat fields need schema homes and a coverage-addendum entry before any migration,
   and the samples then move into the top-level samples folder and the field inventory. Every NAPIX field must have a
   home.
3. Optional, at most 1 to 3 calls in a later check: test `S` against `A` with text found mid-word, and confirm that
   lapsed caveats are never served (for example, re-search `ASSAM` after 20 Nov 2026 to see whether caveat 904,
   filed 19 Aug, has dropped out).
