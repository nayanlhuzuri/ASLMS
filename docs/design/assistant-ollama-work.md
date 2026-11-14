# Design: The Case Assistant split by purpose, and My Work on the sidebar Assistant (local model, round 2 of 2)

```
slug: assistant-ollama-work
status: approved
author: architect
date: 2026-11-13
approved_by: owner, 2026-11-13, as written with the eight owner checks as proposed (approach approved 12 Nov 2026)
```

## Context
Backlog row 189. Round 2 of the local-model Case Assistant. Round 1 (row 188 `assistant-ollama`, migration 0032)
is built and live since 28 Oct 2026, with polish rows 198 and 202 on top.

**What was approved before.** Design `docs/design/assistant-ollama.md`, decisions 19 to 23, approved by the owner on
27 Oct 2026. They cover a fourth scope, `my_work`, shown as the "My Work" tab on the sidebar Assistant page. It has nine
fixed work questions, each mapped to the existing service of its screen and run with the asker's own rights. The
model picks a question and its validated parameters through Ollama tool calling, with a keyword fallback. There are
no model-written queries, and the model never sees note, remark or document contents.

**What the owner added on 12 Nov 2026.** The approach was approved; this design amendment is to be approved; the item
is built right after row 238.
1. **The case page Assistant** (the case's Assistant tab) is about that one case only. It keeps the This Case scope,
   with other cases' court orders for comparison as today, and the "Include This Case's Internal Records" switch as
   built in row 188. The My Cases and All Court Orders scopes leave the case tab.
2. **The sidebar Assistant** has three tabs: My Work (new, this row), My Cases and All Court Orders (as today).
   Existing My Cases and All Court Orders conversations that were started from a case page stay, and are listed on the
   sidebar page.
3. **My Work gains claim questions** beside the nine of decision 20. Each comes from an existing screen's service,
   run with the asker's rights:
   - cases claimed by me, by period (last 7 days, last 30 days, all), from the claim records naming the officer who
     claimed;
   - cases my department has claimed, by period;
   - cases recommended to my department and waiting to be claimed.
4. **Every My Work answer states the count first** (for example "You claimed 14 cases in the last 30 days"), then
   lists at most 25 rows with links.

The trigger: the owner asked the sidebar assistant "how many cases were claimed by me?" and got no proper answer. The
court-records scopes cannot see ownership data.

**What is in place:**
- `services/assistant.py`: scopes `case`, `my_cases` and `research`; transaction A, the call, transaction B; quick
  facts (connector `facts`); the switch; `messages_out` with read-time re-checks; `check` with five counts.
- `services/assistant_ollama.py`: `OllamaConnector`, readiness, `admission()` and the slot.
- `integration/ollama/client.py`: `OllamaReply.tool_calls` is already parsed.
- `tests/fakes/ollama.py`: `FakeOllama`.
- The screens' services this item reads:
  - `custody.held` and `custody.sent` (Case Inbox → With Me and Sent by Me);
  - `my_cases.mine` (My Cases, with the "Claimed by Me" reason from `my_cases.my_conditions`);
  - `calendar.my_calendar` (My Calendar);
  - `alerts.list_for_user` (Alerts);
  - `dashboard.personal_headline` (dashboard);
  - `inbox.claimed` (Case Inbox → Department);
  - `inbox.recommended` (Case Claim → Recommended).
- Portal: `components/assistant/Assistant.tsx`, `lib/assistant.ts` (`scopesFor`), the kit `Tabs`, `DataTable` and
  `ChipGroup`.

**Where things moved since 27 Oct.**
- Row 206 rebuilt the Case Inbox into four tabs: With Me reads `custody.held(scope="me")`, Sent by Me reads
  `custody.sent`, My Cases reads `my_cases.mine(view="all")`, and Department reads `inbox.claimed`.
- Case Claim now has Recommended, Pool and Transfers. There is no "Claimed" tab there any more. The department's
  claimed cases are on Case Inbox → Department, so the owner's "Case Claim → Claimed" is read as that tab
  (decision 6).
- Row 207 added closed cases. With Me leaves them out.

**Not covered:**
- any write from the assistant: no Claim, Send or Assign from an answer;
- work questions on the case tab or in sourcetrace mode;
- free-form questions across ownership data other than the twelve fixed questions;
- follow-up questions that rely on an earlier question (each My Work question stands alone);
- the research rows 250 to 253;
- SourceTrace's boundary;
- model management;
- streaming.

## Decisions

Decisions 19 to 23 of `assistant-ollama` stand except where a decision below amends them. Each amendment is named, so
that the scribe can add an "Amended by `assistant-ollama-work`" line under each one.

1. **The case tab is about its own case only (owner, 12 Nov 2026).**
   - `scopesFor("case")` becomes `["case"]`, so the case tab shows no scope switch.
   - This Case is unchanged:
     - related orders of other cases for comparison (`include_related`);
     - quick facts;
     - the internal-records switch and the suggestion line;
     - Copy to Note.
   - Under the question box, one line and a link take the place of the switch: "For questions across your cases, about
     your own work, or across all court orders, open the Assistant." The link "Open the Assistant" goes to
     `/assistant`.
   - The server is unchanged. It never trusted the origin (`assistant-ollama` decision 4), so `my_cases` and
     `research` remain valid scopes for `POST /assistant/ask` from any client. They are simply no longer offered on
     the case tab. A client sending them gets court information only, as today.
   - Alternative rejected: refusing `my_cases` and `research` when the client says it is on a case page. That flag
     could be forged and would protect nothing.
   - **Amends `assistant-ollama` decision 4 ("Origin")** and decision 10's "scope switch on the case tab", which
     falls away.

2. **The sidebar Assistant has three tabs: My Work, My Cases and All Court Orders (owner, 12 Nov 2026).**
   - The page header's segmented "Search In" switch is replaced by the kit `Tabs`, one entry per tab in the address:
     - `/assistant?tab=my-work`
     - `/assistant?tab=my-cases`
     - `/assistant?tab=court-orders`
   - A tab is shown only when `GET /assistant/status` lists its scope. My Work is offered in ollama and preview modes
     only (decision 19 of `assistant-ollama`, unchanged).
   - With no `tab`, the page opens My Work when it is offered, otherwise My Cases. An unknown `tab` falls back the
     same way.
   - Each tab lists its own conversations (`GET /assistant/conversations?scope=…`, 50, newest first) and opens its
     latest.
   - **Switching tabs never asks the last question again.** The re-ask existed for the case tab's scope switch, which
     is gone. A My Work question asked again in All Court Orders would make no sense.
   - **Existing conversations.** My Cases and All Court Orders conversations started from a case page were always
     created without a case (`case_id` null; the CHECK `ck_assistant_conversations_case_scope`). The sidebar lists
     them already, and nothing is migrated. A test proves it (Tests).
   - **Amends `assistant-ollama` decision 14** (the Assistant page's scope switch).

3. **Twelve work questions: the nine of decision 20 and three claim questions (owner, 12 Nov 2026).**
   - Each question is one entry in the code registry `WORK_QUESTIONS`. It has a key, a label, an example, a strict
     parameter model, the guard of its screen's route, the service it calls, the allow-listed fields, the full-list
     link and the count sentence.
   - Adding a question is a code change with its own test, never a setting (unchanged).

   | # | Key | What it answers | Parameters (validated, `extra="forbid"`) | Service called, with the asker | Guard (as the screen's route) | Full list |
   |---|---|---|---|---|---|---|
   | 1 | `pending_actions` | Files with me that have a pending action | `when`: `overdue` / `due_this_week` / `all` (default `all`) | `overdue`: `custody.held(scope="me", overdue=True)`; `due_this_week`: `my_cases.mine(view="files", action="due_week", closure="open")`; `all`: `custody.held(scope="me")` with rows whose pending action is not `none` (decision 5) | `cases.view_scope` or `cases.view_all` | `/inbox/with-me` (`?overdue=true` for `overdue`) |
   | 2 | `cases_with_me` | Files with me | none | `custody.held(scope="me")` | as 1 | `/inbox/with-me` |
   | 3 | `sent_by_me` | Files I sent or recalled, and whether they are still where I sent them | `period`: `last_7_days` / `last_30_days` / `all` (default `last_30_days`); `still_out`: bool (default false) | `custody.sent(still_out=…, since=…)` (decision 5) | as 1 | `/inbox/sent` (`?earlier=true` unless `still_out`) |
   | 4 | `my_hearings` | Hearings of my cases | `range`: `today` / `tomorrow` / `this_week` / `next_week` / `dates` with `from` and `to` (at most 31 days, within 62 days of today) | `calendar.my_calendar(from_, to)`, kind `hearing` | as 1 | `/calendar?day=<from>` |
   | 5 | `listed_tomorrow` | My cases on tomorrow's cause lists | none | `calendar.my_calendar(tomorrow, tomorrow)`, kind `hearing` | as 1 | `/calendar?day=<tomorrow>` |
   | 6 | `my_due_dates` | My action due dates and next dates to confirm | `range` as 4 | `calendar.my_calendar`, kinds `action_due` and `confirm` | as 1 | `/calendar?day=<from>` |
   | 7 | `unread_alerts` | My unread open alerts | `kind`: an `AlertKind` value or `any` (default `any`) | `alerts.list_for_user(unread=True, status="open", kind=…)` | as 1 | `/alerts?unread=true` (and `&kind=`) |
   | 8 | `new_orders` | New orders in my cases, from my new-order alerts | `days`: 1–30 (default 7) | `alerts.list_for_user(kind="new_order", status="all")`, newest first, kept within `days` (decision 5) | as 1 | `/alerts?kind=new_order` |
   | 9 | `needs_attention` | What needs my attention today | none | `dashboard.personal_headline`: `headline` and `attention` | `cases.view_scope` or `cases.view_all` (the dashboard's `reader`) | `/` |
   | 10 | `claimed_by_me` | Cases I claimed | `period`: `last_7_days` / `last_30_days` / `all` (default `all`) | `my_cases.claimed_by_me(since=…)` (decisions 5 and 6) | `cases.view_scope` (`my_cases._require`) | `/inbox/my-cases` |
   | 11 | `department_claimed` | Cases my department has claimed | `period` as 10 (default `all`) | `inbox.claimed(office=<dept>, case_state="all", claimed_since=…)` for each of the asker's departments (decision 6) | `cases.view_scope`, and a department membership | `/inbox/department?department=<code>` when the asker has the Department tab; otherwise `/inbox/my-cases` |
   | 12 | `awaiting_claim` | Cases recommended to my department and waiting to be claimed | `band`: `strong` / `possible` / `any` (default `any`) | `inbox.recommended(office=<dept>, band=high / medium / None)` for each of the asker's departments where they hold `cases.claim` | `cases.claim` in a department membership (`target_department`'s own rule) | `/claim/recommended?department=<code>` (and `&band=high` or `medium`) |

   - **Changes to decision 20's mappings.** `cases_with_me` now reads With Me's own service (`custody.held`), and
     `pending_actions` reads it for `overdue` and `all`. Since row 206 this is the screen the officer compares the
     answer with. With Me leaves closed cases out, so `due_this_week` passes `closure="open"` to keep the same set.
     `my_cases.mine(view="files")` remains the only service with a due-this-week rule.
   - **The guards.**
     - A missing guard answers with the fixed sentence "You do not have this list." (outcome `no_match`). No service
       runs.
     - For questions 11 and 12, an asker without a department gets "This question is about your department's cases,
       and you do not belong to a department." (outcome `no_match`).
     - A State-wide reader without a department, such as the Super Administrator, gets that sentence too. My Work is
       about the asker's own work, so it never reads another department's lists, even with `cases.view_all`.
   - **Amends `assistant-ollama` decision 20.**

4. **The answer is written by the server: the count first, then the list. The model only picks the question
   (owner, 12 Nov 2026, point 4).**
   - Every My Work answer is built from the service's result with no model wording:
     1. **The count sentence**, from `total`, a fixed template per question (decision 7);
     2. **at most one detail sentence** from figures the same service returns (for example "3 of them are overdue");
     3. **the shown line**: "Showing all 14." or "Showing the first 25 of 41. Open the full list for the rest.";
     4. **the rows**, at most `ASSISTANT_WORK_ROWS` (25), shown as a list with links (decision 10).
   - The answer text names **no case**. Cases appear only in the rows, so the text can never misname one, and it stays
     readable when a row's case later goes out of the reader's sight (decision 9).
   - The model's only part is the choice (decision 8): one tools call.
   - **Amends `assistant-ollama` decision 21, step 4 (the wording call is dropped)**, and decision 22's preview
     template. Reasons:
     - The owner fixed the answer's shape: count first, then the list.
     - A count and a list are facts the server already holds exactly.
     - A second model call adds about 2 s and a second hold of the one slot, and it could state a wrong number or
       name a case wrongly. The owner's test of 27 Oct showed such slips.
     - With no wording call, preview and ollama answers are identical apart from how the question was chosen. So the
       owner's preview check in development tests the real answers.
   - Alternative rejected: keeping the wording call after a server-written count. It would add a second, unchecked
     restatement of the same rows.

5. **How the services are used: called as the screen calls them, with three optional period keywords and one row
   filter.** The adapter (`WorkQuestion.run`) calls the screen's service in a read-only transaction with the asker as
   the user, so visibility, memberships, tiers and `cases.view_private_all` apply exactly as on that screen. On top of
   that, only these are allowed:

   **(a) Three services gain one optional keyword each.** They are service-level only: no route, API parameter or
   portal filter changes. Without the keyword each behaves exactly as today, and a test proves it.
   - `custody.sent(..., since: datetime | None = None)` keeps legs with `created_at >= since`.
   - `inbox.claimed(..., claimed_since: datetime | None = None)` and `inbox.claimed_stmt` keep ownership rows with
     `claimed_at >= claimed_since`.
   - `my_cases.claimed_by_me(session, user, *, since=None, limit=None, offset=None) -> Page` (new, read-only)
     returns the cases of the My Cases tab's "Claimed by Me" reason. It builds its rule from `my_conditions`'
     `claimed` condition, with an optional `claimed_at >= since` inside the same `EXISTS` on the department's active
     primary row. That rule is: the department's active primary ownership, written by the asker (a claim), or reached
     by a transfer the asker accepted.
     - `my_conditions` gains `claimed_since: datetime | None = None` for this. Its other callers pass nothing and are
       unchanged.
     - The rows are ANDed with `visible_case_condition` and `merged_into_case_id IS NULL`, as `mine_stmt` does.
     - They are ordered newest claim first and returned as `{case, claimed_at, office_code, via: "claim" |
       "transfer"}`.

   **(b) A row filter, for two cases only.**
   - `pending_actions` with `when=all` keeps held files whose `card.pending_action` is not `none`.
   - `new_orders` keeps alerts dated within `days`. The service orders newest first, so paging stops at the first
     older row.

   The adapter pages through the service at 100 rows a page and at most `WORK_SCAN_ROWS` (1,000, a constant). If the
   cap is reached, the count says "at least" and `model_info.scan_capped` is true. An officer's own files and alerts
   are far below the cap.

   **Periods** are IST days from the one helper (`rules.today_ist`):
   - `last_7_days`: claimed or sent on or after today − 6, 00:00 IST;
   - `last_30_days`: on or after today − 29;
   - `all`: no bound.

   **Never added:** a new query on any table outside these services, a model-written filter, or a field the screen
   does not show. The `assistant_work` module may not import `notes`, `documents`, `ownership` (the write service),
   `custody.history` or `case_note_drafts` (unit test).
   - **Deviation from `assistant-ollama` decision 20's "Service called (unchanged)"**, flagged for the owner. The three
     keywords are the smallest change that answers "by period" from the screens' own services. The owner's 12 Nov
     direction asks for claim counts by period, and no claimed-date filter exists on any screen today.

6. **What the claim questions count (owner, 12 Nov 2026, point 3; owner check 1).**
   - **`claimed_by_me`** counts the cases shown on Case Inbox → My Cases with the badge "Claimed by Me". These are
     cases the asker's department holds as primary owner, where the asker made the claim or accepted the transfer
     that brought the case to the department.
     - Disposed and closed cases count. The period runs from the date of that claim or acceptance.
     - Not counted: a watcher claim (a second department's claim on a case another department holds), and a case the
       asker claimed that has since been transferred to another department. Neither is on the asker's My Cases tab.
     - Each row says "Claimed" or "Transfer Accepted" (`via`), and gives the date.
     - Reason: the officer can open My Cases and see the same set. This answers the owner's "from the claim records
       naming the officer who claimed": `case_ownership.actor_user_id`, with `ownership_transfers.decided_by_user_id`
       for transfers.
   - **`department_claimed`** counts the rows of Case Inbox → Department (`inbox.claimed`): primary and watcher rows,
     active and disposed (`case_state="all"`), claimed in the period.
     - A whole-department reader (`visibility.whole_department`) gets every row.
     - Any other officer gets what the same service shows them: cases assigned to them or to their unit. The count
       sentence then says "that you can see".
     - The service applies this rule itself; the adapter only reads `whole_department` to choose the words.
   - **`awaiting_claim`** counts the Recommended tab's rows (status `recommended`, `merged_into_case_id` null), with
     the strong and possible counts from two more calls with `band`.
     - Recommendation reasons and scores are never shown here (decision 20's "never recommendation reasons" stands).
     - The band is shown as "Strong" or "Possible".
     - Each row links to the case in the Case Claim modal (`/claim/recommended?department=<code>&case=<ref>`), where
       the person decides. **Recommend-and-claim stands:** the assistant never claims, and an answer holds no Claim
       button.
   - **Several departments.** Questions 11 and 12 run once for each department among the asker's memberships, each
     department once, in membership order, where the guard holds in that membership.
     - Rows are combined in department order, each in the service's own order, and capped at 25 in all. The total is
       the sum.
     - The count sentence names each department by its office name when there are two or more (decision 7).
     - Departments where the guard fails are left out silently. If none remains, the answer is "You do not have this
       list."

7. **The count sentences: fixed templates in code, with plurals and IST dates.** The department is named by its
   office name (`offices.name`), never its code. Where `n` is 0 the sentence uses "no" ("You claimed no cases in the
   last 30 days.").

   | Key | Count sentence | Detail sentence (when non-zero) |
   |---|---|---|
   | `pending_actions` | "You have n files with a pending action." / "n files with you are overdue." / "You have n files with a pending action due in the next 7 days." | `all`: "k of them are overdue." (the overdue count from `custody.held(overdue=True)`) |
   | `cases_with_me` | "n case files are with you." | "k have a pending action; j are overdue." (from the rows' cards, or the counts when more than 25) |
   | `sent_by_me` | "You sent or recalled n files in the last 30 days." / "… in the last 7 days." / "You have sent or recalled n files in all." / with `still_out`: "n files you sent are still where you sent them." | without `still_out`: "k are still where you sent them." (rows with `current` true; counted from a second call with `still_out=True` and the same `since`) |
   | `my_hearings` | "You have n hearings <range in words> (<from> to <to>)." | none |
   | `listed_tomorrow` | "n of your cases are on tomorrow's cause lists (<date>)." | none |
   | `my_due_dates` | "You have n due dates <range in words>." | "k pending actions and j next dates to confirm." |
   | `unread_alerts` | "You have n unread alerts." / "You have n unread <kind label> alerts." | none |
   | `new_orders` | "You have n new-order alerts in the last <days> days." | "They name k cases." |
   | `needs_attention` | "n things need your attention today." | the headline figures in one sentence, for example "Files with you: 12; overdue: 3; hearings in the next 7 days: 5." |
   | `claimed_by_me` | "You claimed n cases in the last 30 days." / "… in the last 7 days." / "You have claimed n cases in all." | "Counted as on your Case Inbox's My Cases tab: cases your department holds that you claimed or whose transfer you accepted." (always, as a second line) |
   | `department_claimed` | "<Department> claimed n cases in the last 30 days." (+ " that you can see" when not whole-department) / two or more: "Your departments claimed n cases in the last 30 days: <Dept A> k, <Dept B> j." | none |
   | `awaiting_claim` | "n cases are recommended to <Department> and waiting to be claimed." / two or more: "n cases are recommended to your departments and waiting to be claimed: <Dept A> k, <Dept B> j." | "s strong and p possible." |

   - Dates are written as on the portal: "Fri 14 Nov 2026".
   - The range words are "today", "tomorrow", "this week", "next week", and "from <date> to <date>".
   - The templates live in `services/assistant_work.py`. A unit test covers each template at 0, 1 and many.

8. **Choosing the question: one tools call to the local model, the keyword table as the fallback, and no 503 for My
   Work.**
   1. **Admission without refusal.** My Work takes the model's slot with a short wait (`WORK_SLOT_WAIT_SECONDS`, 5, a
      constant) through a new `OllamaConnector.try_admission(wait)`.
      - It returns the slot, or `None` with the reason: `loading`, `unavailable` or `busy`. It never raises.
      - Like `readiness()`, it may start a load of a model that is held but not loaded.
      - On `None` the keyword table decides at once. So a My Work question is never refused with `assistant_loading`,
        `assistant_unavailable` or `assistant_busy`.
      - **Amends `assistant-ollama` decision 21**, whose fallback named only a model that failed during the call.
        Reason: the answer does not depend on the model, so making the officer wait or retry would gain nothing.
   2. **The tools call**, as decision 21 step 1, with twelve functions:
      - one `POST /api/chat` with `tools`, `think: false`, `temperature` 0, `num_ctx` 4096 and `num_predict` 200;
      - the system line "Choose the one function that answers the officer's question about their own work. If none
        fits, call no function. Today is <IST date, weekday>.";
      - the question;
      - no history and no case data;
      - a timeout of `min(10 s, ASSISTANT_OLLAMA_TIMEOUT_SECONDS)`.

      Exactly one call, with a name on the allow-list and arguments that pass the question's strict model, is a valid
      choice (`chosen_by: model`). The date bounds of `dates` are checked against the IST today.
   3. **The keyword table** (`keyword_choice(question, today)`) decides when there is no valid choice. That covers no
      call, several calls, an unknown name, bad arguments, a timeout, an unavailable model, or `None` from admission.
      - It is an ordered list of rules, specific phrases before general ones. A match on two questions at the same
        rank is `ambiguous`.
      - The nine rows of decision 21 stay. Three are added:

        | Phrases (any) | Question |
        |---|---|
        | "claimed by me", "i claimed", "did i claim", "my claims", "have i claimed" | `claimed_by_me` |
        | "department claimed", "department has claimed", "we claimed", "our department claimed", "claimed by my department", "claimed by our department" | `department_claimed` |
        | "waiting to be claimed", "to be claimed", "to claim", "recommended to", "recommendations" | `awaiting_claim` |

        "claimed" with "department", "we" or "our" goes to `department_claimed` before the `claimed_by_me` rule
        reads "my", so "how many cases has my department claimed" is not `claimed_by_me`.
      - The period words are:
        - "7 days", "week" or "past week" → `last_7_days`;
        - "30 days", "month" or "past month" → `last_30_days`;
        - otherwise each question's default.
      - The band words: "strong" → `strong`; "possible" → `possible`.
      - Dates still come only from fixed words, with no free date parsing.
      - With `chosen_by: keyword` the answer is the same as with the model.
   4. **No question.** If the keywords match none, or match ambiguously, the answer is the fixed `no_match` text, and
      no service runs. Decision 21's text is extended with the claim questions: "This tab answers questions about
      your own work: pending actions and due dates, cases with you or sent by you, your hearings and tomorrow's
      listings, unread alerts, new orders, what needs attention, the cases you or your department claimed, and the
      cases waiting to be claimed. Try one of the examples, or ask about court orders in My Cases or All Court
      Orders." (`chosen_by: none`).
   5. **Preview mode** uses the keyword table only (decision 22, unchanged), with the same services, caps, sentences
      and rows.

   - **What the model can do:** pick one of twelve functions with validated parameters, run with the asker's own
     rights. It reads nothing and changes nothing. Its reply is stored verbatim in `response` (never shown).

9. **What is stored, and the re-check when shown.**
   - **The answer row** has:
     - `mode`: the assistant's mode (`ollama` or `preview`);
     - `connector` `work` (like `facts`, a stand-in name: no connector wrote it);
     - `outcome`: `answered` (rows, or the zero-rows sentence) or `no_match` (no question, a missing guard, no
       department);
     - `content`: the server's text of decision 4;
     - `response`: the tools reply, or null;
     - `model_info`: `{"engine": "work_list", "work_version": 1, "question": key | null, "params": {…}, "chosen_by":
       "model" | "keyword" | "none", "model": name | null, "choice_fallback": null | "no_call" | "invalid" |
       "timeout" | "unavailable" | "loading" | "busy", "total", "shown", "scan_capped", "departments": [codes],
       "durations": {"choose_ms", "run_ms"}}`. These are numbers, keys and labels only.
   - **Rows** are stored as citations, as `assistant-ollama` decision 23 sets out: `source_kind` `work_row`, `label`
     `S1`.., `cited` true, `case_id` (null for an alert without a case), and `work`:
     `{question, list_label, as_of, fields}`.
     - `fields` holds only the question's allow-listed keys (decision 10), as a snapshot, because these facts change.
     - `awaiting_claim` and `department_claimed` rows add `department` (the office code) inside `fields`.
   - **Re-check at every read.** One batched `visible_case_condition` query covers all the row cases of a thread:
     - A row whose case the reader can no longer see shows "A case you can no longer open" and no fields.
     - **The answer text stays**, because it names no case (decision 4). This **amends `assistant-ollama` decision
       23**, which hid the whole answer. That rule protected model-written text that might quote a case, and here
       there is none.
   - The snapshot is never refreshed silently. The row shows "as of <time>", and the reader asks again for current
     facts.
   - The conversation is readable by its asker only (unchanged).

10. **The allow-listed fields of each question.** Only these keys may be in `fields`, may reach the portal, and may
    be counted by `check`. A unit test pins the table and refuses `remark`, `body`, `note`, `text`, `reasons`,
    `ref_no` and `score_signals` in any entry.
    - **Every row:** `case_no`, `cnr`, `parties` (petitioner v respondent summary, at most 160 characters), and
      `case_ref` (the id the case link is built from).
    - **`pending_actions` and `cases_with_me`:** `pending_action_label`, `due_date`, `overdue_days`, `due_soon`,
      `since`, `sent_by` (name, designation, office name).
    - **`sent_by_me`:** `date`, `action` (`Sent` or `Recalled`), `to` (office name and designation),
      `pending_action_label`, `due_date`, `still_there` (the service's `current`; null when the sender can no longer
      open the case).
    - **`my_hearings` and `listed_tomorrow`:** `date`, `court_no`, `item_no`, `bench`, `approximate`.
    - **`my_due_dates`:** `date`, `kind_label` (`Pending Action Due` or `Next Date to Confirm`),
      `pending_action_label`.
    - **`unread_alerts` and `new_orders`:** `date`, `kind_label`, `severity`, `title`. Never `body` or `note`.
    - **`needs_attention`:** `kind_label`, `title`, `date`, `detail` (the dashboard's own one-line detail, such as
      "Disposed by the court on …"), and `overdue_days`.
    - **`claimed_by_me`:** `claimed_on`, `via` (`Claimed` or `Transfer Accepted`), `department`, `status`.
    - **`department_claimed`:** `claimed_on`, `department`, `role` (`Primary` or `Watcher`), `assigned_to` (unit
      name and officer name, as on the Department tab), `status`.
    - **`awaiting_claim`:** `department`, `band` (`Strong` or `Possible`), `next_hearing` (the case summary's next
      hearing date and its kind), `last_listed_on`.

    **Never:** custody remarks (including the asker's own), note text, document text or names, alert bodies,
    recommendation reasons or scores, or `ref_no`. **Amends `assistant-ollama` decision 20** ("Fields that may reach
    the model"): with no wording call, the fields reach no model at all, only the asker's own screen.

11. **A "My Work" suggestion in My Cases and All Court Orders (the owner's trigger).**
    - In My Cases or All Court Orders, in a mode where My Work is offered, the keyword table of decision 8 runs on the
      question after the court answer is stored. It is deterministic and makes no model call.
    - When it picks one question unambiguously, and the asker passes that question's guard, the answer is flagged
      `suggest_work` (stored in `model_info`).
    - The portal then shows: "This looks like a question about your own work. Ask it in My Work?", with the button
      "Ask in My Work". The button opens `/assistant?tab=my-work` and asks the same question there, in a new My Work
      conversation.
    - It is a deliberate click. Nothing is asked again by itself, and the court answer stands.
    - It mirrors the internal-records suggestion of row 188.
    - Alternative rejected: sending such questions to My Work automatically. A wrong guess would answer a court
      question from lists, and the scopes stay explicit (decision 19 of `assistant-ollama`).

12. **Audit and logging: keys, parameters and counts, never text.**
    - `assistant.asked` (transaction A) adds `scope: "my_work"`. The question is chosen after A, so the chosen key
      moves to `assistant.answered`.
    - `assistant.answered` adds:
      - `work_question` (key or null);
      - `work_params` (enums, dates and small numbers);
      - `chosen_by`;
      - `choice_fallback`;
      - `work_rows` (rows stored);
      - `work_total`;
      - `departments` (codes).
    - **Amends `assistant-ollama` decision 18**, which put the key on `assistant.asked`.
    - One INFO line per tools call carries the model, duration, chosen key or fallback reason, and the question's
      digest.
    - No question text, row field or answer text appears in `audit_log` or in a log line.
    - The audit log screen shows these under the existing "Case Assistant" group. No new action is added.

13. **Limits, time and what My Work is not.**
    - A My Work question counts toward the hourly limit (30) and the one-unanswered-question rule, like a quick fact.
    - The whole question stays within `ASSISTANT_TIMEOUT_SECONDS` (45):
      - the choice gets at most 10 s;
      - the services run in one read-only transaction (`SET TRANSACTION READ ONLY`) with `SET LOCAL
        statement_timeout` of 10 s;
      - a service that runs out of time stores a `failed` answer, family `timeout`, with "Your lists took too long to
        read; try again."
    - **Not available:**
      - in sourcetrace mode: 422 `scope_unavailable` before anything is stored (decision 19, unchanged; owner check 5);
      - when off: 503 `assistant_off`;
      - with a case: 422 `scope_mismatch`.
    - `include_related` is ignored for `my_work`.
    - **The assistant informs and never acts.** No row carries a Claim, Send, Assign or Mark Read control. The links
      open the case page or the Case Claim modal, where the person acts. Reading an alert through My Work does not
      mark it read.

14. **Plan and earlier variations.**
    - The plan (§5.9) describes the Case Assistant as a chat "on every case page … about that case". Decision 1
      brings the case tab back to that.
    - My Work on the sidebar is the owner's addition of 27 Oct 2026, already recorded as a variation in the software
      documentation's 13.2 ("the sidebar Assistant's My Work tab answers questions about the officer's own pending
      actions, hearings, alerts and new orders from the existing lists, never from note text").
    - This item extends that row with "and the cases the officer or the department claimed, and the cases waiting to
      be claimed; the count and list are written by ASLMS from the lists, the local model only chooses which list".
    - No new deviation from CLAUDE.md. Its "Never send to SourceTrace" bullet gains the My Work sentence that
      `assistant-ollama` decision 1 wrote and round 1 left out:
      > On the Assistant page's My Work tab ASLMS states the asker's own work facts from a fixed list of existing
      > screens' services (Case Inbox, Case Claim, My Calendar, Alerts, dashboard), never the contents of notes,
      > remarks or documents; the local model only chooses which list, and writes no query and no answer text
      > (owner, 27 Oct and 12 Nov 2026; design `assistant-ollama-work`).

## Data
**Migration** `00NN_assistant_my_work.py`, hand-written. It takes the next free number at build time: **0036** if
built before row 209 `totp-authenticator`, whose design then takes the next one. The developer sets `down_revision`
to main's head and records the number. The integrator re-points `down_revision` if the order changes at merge.
- `ALTER TYPE assistant_scope ADD VALUE IF NOT EXISTS 'my_work'`, in an autocommit block, as 0017, 0023 and 0024 do.
  The domain enum `AssistantScope` gains `MY_WORK = "my_work"`.
- The downgrade stops with a message while any conversation has scope `my_work`. The value itself stays, because
  PostgreSQL cannot drop an enum value; this is recorded in the migration's docstring.
- **No other change:** no table, column, index, grant, trigger, `ref_*` code or function. The existing CHECK
  `ck_assistant_conversations_case_scope` keeps `case_id` null for `my_work`, and
  `ck_assistant_conversations_internal_case` keeps `internal_included_at` null. The mode CHECK of
  `assistant_messages` already admits `ollama` and `preview`. `assistant.use` covers the endpoints.

**`docs/schema/schema.md`, the `assistant_conversations` paragraph.** `scope` becomes:
> scope (`assistant_scope`: `case`, `research`, `my_cases` — `my_cases` added by 0024 — and `my_work` — added by 00NN,
> the sidebar Assistant's My Work tab, ollama and preview modes only, never with a case)

**`docs/schema/schema.md`, the `assistant_messages` paragraph.** These places change; the class (`transaction`,
append-only), FKs, CHECKs and grants are unchanged.
- **`connector`:** add `work` — "a My Work answer written by ASLMS from the asker's lists, design
  `assistant-ollama-work`".
- **`citations`:** add to the list of keys `work? ({question, list_label, as_of, fields}; work_row only; fields from
  the per-question allow-list of design assistant-ollama-work decision 10, never a remark, note, document or alert
  body, recommendation reason or score)`. Add `work_row` to the `source_kind` list. Add the sentence: "`work_row`
  appears only on answers of scope-`my_work` conversations, whose connector is `work`."
- **`model_info`:** add `work {"engine": "work_list", "work_version": 1, "question", "params", "chosen_by",
  "choice_fallback", "model", "total", "shown", "scan_capped", "departments", "durations"}`; `suggest_work` on a My
  Cases or All Court Orders answer.
- **`response`:** "SourceTrace's or Ollama's reply verbatim (for a `work` answer, the tools reply that chose the
  question), never shown".
- **The closing sentences** gain: "A `work` answer draws on no model text: its content is written by ASLMS from the
  asker's own lists, and its rows are snapshots of allow-listed fields, re-checked for case sight at every read."

An "As built by `assistant-ollama-work`" line goes under the `assistant-ollama` line after the build.

**`services/assistant.check`** gains count **(6)**: `work_row` citations on a conversation whose scope is not
`my_work`, on an answer whose connector is not `work`, or whose `fields` hold a key outside their question's
allow-list. `aslms assistant check` prints six counts and exits 1 if any is not 0.

## Services
**`backend/aslms/services/assistant_work.py`** (new). It imports no connector, no `integration.ollama`, and none of
`notes`, `documents`, `ownership`, `custody.history`, `stages` or the draft tables.
- `WorkQuestion` (frozen dataclass), with:
  - `key`, `label`, `example`;
  - `params: type[BaseModel]` (`extra="forbid"`);
  - `guard`: `any_of` functions, plus a department rule for 11 and 12;
  - `run(session, user, params, *, now, rows_cap) -> WorkResult`;
  - `list_label`;
  - `full_list_href(params, result) -> str`;
  - `count_sentence(result, params) -> str` and `detail_sentence(result, params) -> str | None`;
  - `none_sentence` (kept for zero rows where the count sentence alone reads badly);
  - `keywords`.
- `WORK_QUESTIONS`: the ordered registry of the twelve (decision 3). `FIELDS[key]`: the allow-lists (decision 10).
- `WorkResult` holds:
  - `rows`: dicts of allow-listed keys plus `case_id`;
  - `total`;
  - `extra`: the figures the detail sentence uses;
  - `as_of`, `list_label`, `departments`, `scan_capped`;
  - `whole`: `department_claimed` only.
- `available(session, user) -> list[WorkQuestion]`: the questions whose guard the asker passes, for the status
  chips.
- `tool_schemas() -> list[dict]`: Ollama `tools`, one function per question, with JSON schemas of enums, `YYYY-MM-DD`
  dates and `additionalProperties: false`.
- `validate_choice(tool_calls, today) -> tuple[str, BaseModel] | None`.
- `keyword_choice(question, today) -> tuple[str, BaseModel] | None | Literal["ambiguous"]`.
- `answer(session_factory, user, key, params, *, rows_cap, now) -> WorkAnswer`:
  - checks the guard, which gives the fixed sentence when it fails;
  - opens one read-only session with `statement_timeout`;
  - runs the question and builds `content` (decision 4) and the citations (decision 9).
- `period_start(period, today) -> datetime | None`, in IST.

**Extensions of existing services** (decision 5a). Service-level only, with defaults keeping today's behaviour:
- `custody.sent(..., since=None)`;
- `inbox.claimed_stmt(..., claimed_since=None)` and `inbox.claimed(..., claimed_since=None)`;
- `my_cases.my_conditions(session, user, *, claimed_since=None)` and the new `my_cases.claimed_by_me(session, user,
  *, since=None, limit=None, offset=None) -> Page`, which requires `cases.view_scope` like `mine`.

**`backend/aslms/services/assistant_ollama.py`:**
- `try_admission(wait: float) -> tuple[Slot | None, str | None]` (decision 8.1);
- `async choose_work(question, today, *, timeout) -> tuple[OllamaReply | None, str | None]`: the tools call. It
  returns the reply, or the failure family. It reads no database.

  Decision 21's `word_work` is **not built** (decision 4).

**`backend/aslms/services/assistant.py`:**
- `SCOPES` gains `my_work`.
- `status` lists `scopes` by mode: ollama and preview give `case`, `my_cases`, `research` and `my_work`; sourcetrace
  gives the first three. It adds `work_questions`: `[{key, label, example}]` from `assistant_work.available(...)` in
  ollama and preview mode, otherwise `[]`.
- `ask`: for scope `my_work`:
  - it refuses sourcetrace (`ScopeUnavailable`, 422 `scope_unavailable`) and a case (`ScopeMismatch`) before
    anything is stored;
  - transaction A as today: clean question, user lock, in-flight, hourly limit, conversation, the question row, and
    `assistant.asked` with `scope_info {kind: "my_work"}`. A helper shared with `_prepare` avoids duplicating these
    steps. No focus cases, filings or `AskRequest` are built;
  - then the choice (decision 8), `assistant_work.answer`, and transaction B, which stores the answer with connector
    `work` and writes `assistant.answered` with decision 12's fields;
  - the slot is released after the choice, because the services need no model.
- After B, for a `my_cases` or `research` answer in ollama or preview mode: `suggest_work`, set from
  `keyword_choice(q, today)` returning one key whose guard the asker passes (decision 11).
- `_map_citations` and `messages_out` handle `work_row`:
  - `CitationOut.work` is `{list_label, as_of, fields}`, with `fields` re-filtered through `FIELDS[question]` at read
    time;
  - `open` is `{kind: "case_tab", path: "/cases/<ref>"}` for a case the reader can open, or `{kind: "claim", path:
    "/claim/recommended?department=<code>&case=<ref>"}` for an `awaiting_claim` row;
  - a row whose case is out of sight gets `unavailable` and no fields (decision 9).
- `MessageOut.work`: `{question, label, chosen_by, total, shown, list_label, full_list_href, scan_capped} | null`.
- `check`: count (6) (Data).
- The existing unit test that the assistant modules import no write service gains `assistant_work`.

**`backend/aslms/cli/assistant.py`:**
- `ask --my-work` (refused in prod, as `ask` is) prints the chosen key, the parameters, `chosen_by`,
  `choice_fallback`, the count sentence, and the rows' case numbers;
- `check` prints six counts.

**Portal** (`frontend/src/components/assistant/Assistant.tsx`, `lib/assistant.ts`, `lib/messages.ts`):
- **The case tab:** `scopesFor("case")` is `["case"]`, so no switcher is shown, plus the line and link of decision 1.
  The `changeScope` re-ask path is removed.
- **The sidebar page:** the kit `Tabs` with `?tab=` (decision 2), each tab with its own conversation list.
- **My Work tab:**
  - the scope note "Answers from your own lists: Case Inbox, Case Claim, My Calendar, Alerts and your dashboard.
    Note text, remarks and documents are never used here.";
  - the example chips from `work_questions`: the first six shown, then a ghost button "More Examples (n)" showing the
    rest.
- **A work answer** shows:
  - the badge "From Your Lists";
  - "Chosen by the Local Model" or "Matched by Keywords" as a muted line;
  - the text;
  - the rows as a kit `DataTable` (stacking as cards on phones, row 115's rule), with the columns of the question
    from a `T.assistant.workFields` label map and the case number linked through `open`;
  - "as of <time>";
  - "Open the Full List" (a link to `full_list_href`);
  - "A case you can no longer open" for a hidden row.

  It shows no `[S#]` markers, no "Sources (n)" button and no Copy to Note: the rows are the answer.
- **The suggestion line** of decision 11 on an answer flagged `suggest_work`.
- **Words:** every label is in Title Case through the label helper, and every server code goes through
  `labelFor`. The wording guards and the "allot" guard cover the new texts.

**Documents** (the developer, with the scribe for the log):
- `CLAUDE.md`: the My Work sentence of decision 14.
- `docs/claude_ASLMS_design_decisions.md`: a dated entry.
- `docs/ASLMS_Process_Workflows.md` section 4.9: the case tab is about its case, the three sidebar tabs, My Work and
  its twelve questions, and the count first.
- `docs/ASLMS_Software_Documentation.docx` through `build.js`: chapter 6 (the two assistants by purpose, My Work)
  and the 13.2 row extended as decision 14 says; regenerate and check `TOC_PAGES`.
- `docs/operations.md` section 20: My Work answers when the model is down (keywords), and `aslms assistant ask
  --my-work`.
- `docs/schema/schema.md` (Data) and `.env.example` (Jobs).

## API
All Case Assistant endpoints need **`assistant.use`** (`Permission.ASSISTANT_USE`), as today. Each work question also
applies its own screen's guard inside the service (decision 3). There is no new route.

- **`GET /assistant/status`:**
  - `scopes`, by mode (Services);
  - new `work_questions: [{key, label, example}]`, holding only the questions the caller may ask;
  - the rest unchanged.
- **`POST /assistant/ask`:**
  - `scope` gains `"my_work"`. The body still forbids extra fields. It carries no question key, because the server
    chooses.
  - Errors:
    - 422 `scope_unavailable` in sourcetrace mode;
    - 422 `scope_mismatch` with a `case`;
    - 503 `assistant_off`;
    - the existing 422 or 429 refusals (`bad_question`, `conversation_full`, `question_in_flight`,
      `assistant_limit`);
    - never `assistant_loading`, `assistant_unavailable` or `assistant_busy` for `my_work` (decision 8.1).
  - The answer adds `work` (as `MessageOut.work`) and `suggest_work` (bool).
- **`GET /assistant/conversations`:** `scope=my_work` is accepted. Items are unchanged: titles and counts only.
- **`GET /assistant/conversations/{id}`:** `MessageOut` gains `work` and `suggest_work`. `CitationOut.source_kind`
  gains `work_row`, with `work: {list_label, as_of, fields}` and `open` as in Services. `AssistantOpenOut.kind` gains
  `claim`.
- Visibility: every row comes from the screen's service run as the caller, and every row's case is re-checked at each
  read.
- The OpenAPI snapshot and `frontend/src/lib/api/schema.d.ts` are regenerated.

## Jobs
None. Questions are answered in the request.

Settings (`core/config.py`, and `.env.example` under "The Case Assistant"):
- `ASSISTANT_WORK_ROWS=25` (5–25): the rows stored and shown per My Work answer.

The owner's 25 is the upper bound. The choice timeout (10 s), the slot wait (5 s) and the scan cap (1,000 rows) are
constants in `assistant_work.py`.

## Tests
No test calls a real model. `FakeOllama` gains scripted `tool_calls` replies, and the test settings keep
`ASSISTANT_OLLAMA_URL` at `http://127.0.0.1:9`.

**Database (`backend/tests/db/test_assistant_work.py`, the `world` fixture with two departments, a directorate and
officers of each):**
- **`test_each_work_question_equals_its_screen`:** for each of the twelve keys and each parameter value, the stored
  rows and `total` equal what the screen's own service returns to the same asker with the same arguments, capped at 25:
  - `custody.held` for With Me;
  - `custody.sent` for Sent by Me;
  - `my_cases.mine` with the "claimed" reason for `claimed_by_me` with `all`;
  - `inbox.claimed` for the Department tab;
  - `inbox.recommended` for Recommended;
  - `calendar.my_calendar`;
  - `alerts.list_for_user`;
  - `dashboard.personal_headline`.
- **`test_claimed_by_me_counts_claims_and_accepted_transfers_in_period`:** the asker's claims 3 and 20 days ago, a
  transfer accepted 5 days ago, and a colleague's claim. The counts are 2 for `last_7_days` and 3 for
  `last_30_days`. The colleague's claim never counts. Also not counted: a watcher claim, and a case the asker claimed
  that was then transferred away. The answer starts "You claimed 2 cases in the last 7 days.".
- `test_claimed_by_me_matches_my_cases_claimed_badge`: the `all` set equals the My Cases rows whose reasons include
  `claimed`.
- **`test_department_claimed_whole_reader_and_directorate_officer`:** the department admin sees every row of the
  period. A directorate officer sees only rows assigned to their unit or to them, and the sentence says "that you can
  see". A State-wide reader with no department gets the no-department sentence.
- **`test_awaiting_claim_needs_cases_claim_and_never_claims`:**
  - Without `cases.claim`: "You do not have this list."
  - With it: the strong and possible counts are stated.
  - After the question, no `case_ownership`, `recommendations` status, alert or custody row has changed.
  - No Claim control is in the answer shape.
- `test_several_departments_summed_and_named`: an officer in two departments gets "Your departments claimed n cases …:
  A k, B j", with rows in membership order, capped at 25.
- **`test_other_officers_items_never_appear`:** officer Y's file, sends, claims and alerts never appear in officer X's
  answers for any key.
- **`test_private_remark_text_never_appears`:** a `private_to_office` remark, the asker's own remark, a note body, an
  internal upload's text, an alert body and a recommendation reason, each with a planted word, appear in no stored
  citation, answer text, request body to the fake, audit row or log line.
- **`test_tool_choice_valid_and_invalid`:** a valid call gives `chosen_by: model`. Each of these falls back to the
  keywords with the right `choice_fallback`:
  - no call;
  - two calls;
  - an unknown name;
  - an extra argument;
  - an out-of-range date;
  - `days` = 999;
  - a name naming SQL.

  No match, or an ambiguous match, gives the fixed text with no service run.
- **`test_my_work_never_503_when_model_loading_busy_or_down`:** with each state scripted, the answer is
  `chosen_by: keyword` with `choice_fallback` `loading`, `busy` or `unavailable`. Nothing is refused, and the fake
  gets no chat.
- `test_answer_text_written_by_server_count_first`: the content's first sentence is the count sentence. No second chat
  request is sent to the fake. The text names no case number.
- `test_zero_rows_sentence`, `test_rows_capped_and_shown_line` (41 rows give 25 rows and "Showing the first 25 of
  41."), and `test_scan_cap_says_at_least`.
- `test_period_boundaries_ist`: a claim at 23:59 IST six days ago counts in `last_7_days`; one at 23:59 seven days ago
  does not.
- **`test_services_unchanged_without_new_keywords`:** `custody.sent`, `inbox.claimed`, `my_conditions` and their
  routes return the same rows as before for existing fixtures.
- `test_my_work_refused_with_case_in_sourcetrace_and_off`: 422 `scope_mismatch`, 422 `scope_unavailable` and 503
  `assistant_off`. Nothing is stored.
- `test_my_work_in_preview_same_answer_as_ollama_keyword`.
- `test_work_row_reread_hides_row_keeps_text`: the asker loses sight of one row's case. That row names nothing, and the
  text and the other rows stay.
- `test_suggest_work_on_court_scopes`: "how many cases were claimed by me?" in My Cases is answered from court records
  as today and flagged `suggest_work`, with no extra model call. A court question is not flagged.
- `test_reading_alerts_through_my_work_marks_nothing_read`, and `test_work_session_is_read_only` (an attempted write
  inside `run` raises).
- `test_my_work_counts_toward_hourly_limit`.
- `test_my_work_audit_keys_params_counts_no_text`.
- `test_check_counts_work_row_outside_my_work_or_extra_field` (six counts).
- `test_case_tab_conversations_of_other_scopes_listed_on_page`: a `my_cases` and a `research` conversation created
  with the case tab's former flow (no case) are returned by `GET /assistant/conversations?scope=…` for the page.
- `test_migration_00NN_my_work_up_down`: the downgrade stops while a `my_work` conversation exists.

**Unit (`backend/tests/unit/test_assistant_work.py`):**
- `test_work_registry_fields_allow_list_has_no_remark_body_text_reason_or_score`;
- `test_assistant_work_imports_no_write_or_text_service`;
- `test_tool_schemas_strict` (12 functions, `additionalProperties: false`, enums);
- `test_keyword_choice_table`:
  - each example chip maps to its question;
  - the owner's sentence "how many cases were claimed by me?" maps to `claimed_by_me` with `all`;
  - "how many cases has my department claimed in the last 30 days" maps to `department_claimed` with
    `last_30_days`;
  - "which cases are waiting to be claimed" maps to `awaiting_claim`;
  - date and period words map as decision 8 says;
  - ambiguity is reported;
- `test_count_sentences_plurals_and_departments` (0, 1, many; one and two departments);
- `test_period_start_ist`;
- `test_settings_work_rows_bounds`.

**API (`backend/tests/db/test_api_assistant.py` additions):**
- `test_status_scopes_by_mode_and_work_questions_by_guard`;
- `test_ask_my_work_shape_work_and_suggest_work`;
- `test_thread_work_row_citation_shape_and_open_kinds`;
- `test_endpoints_need_assistant_use` (unchanged).

**Portal (`assistant.test.tsx` additions):**
- the case tab has no scope switch and shows "Open the Assistant";
- the sidebar's three tabs come from `scopes`, with My Work first in ollama and preview modes, missing in sourcetrace
  mode, and `?tab=` honoured with its fallback;
- switching tabs asks nothing again;
- the My Work note;
- six chips and "More Examples (n)";
- a work answer with "From Your Lists", the chosen-by line, the count sentence, the `DataTable` rows with case links,
  "as of", "Open the Full List", a hidden row in words, and no markers, Sources button or Copy to Note;
- the suggestion line with "Ask in My Work" opening the My Work tab and asking there;
- the labels guard keys for `workFields`.

The `uicheck` fixtures gain `/assistant?tab=my-work` with an answered work question, at 375, 768, 1024 and 1280 px,
and the case tab without its switch.

## Verification
1. `ruff check` is clean and `pytest -q` is green. In `frontend/`, `npm test`, `npm run lint` and `npm run build` are
   green. CI has no Ollama.
2. Migration: upgrade, downgrade and upgrade on a scratch database. On the dev database, only the integrator's
   `migrate` step after the merge.
3. The screen check on a private network against temporary images (runbook section 16): 0 findings on the new
   fixtures.
4. **The owner's live check** (`ASSISTANT_MODE=ollama`, the court-data switch carried on every `up`):
   - `docker compose exec api aslms assistant ask --user <an officer who has claimed cases> --my-work "how many cases
     were claimed by me?"` prints `claimed_by_me`, `period=all` and `chosen_by` `model` (or `keyword` with the
     reason). The count equals the number of rows with the "Claimed by Me" badge on that officer's Case Inbox → My
     Cases.
   - "How many cases has my department claimed in the last 30 days?" for a department admin equals the Department
     tab's rows claimed since today − 29, counted by hand from its Claimed On column.
   - "Which cases are waiting to be claimed?" equals the Recommended tab's count, with the strong and possible counts.
   - "Which of my cases has a pending action due this week?" matches My Cases filtered to due this week. "What needs
     my attention today?" matches the dashboard.
   - With Ollama stopped, the same questions answer by keywords, with no "busy" or "starting" refusal.
   - Record whether `qwen3.5:4b` returned `message.tool_calls` for the `tools` request, and its shape, in the
     decisions log. If it never does, every choice falls back to keywords. That is still correct, but it is reported.
5. **The owner's browser check** at 375, 768 and 1280 px:
   - the case Assistant tab with This Case only and the "Open the Assistant" link;
   - the sidebar Assistant with My Work, My Cases and All Court Orders;
   - the old My Cases conversations started from a case page listed in My Cases;
   - a My Work answer with the count first, the rows with links, and "Open the Full List";
   - the "Ask in My Work" suggestion after asking "how many cases were claimed by me?" in My Cases.
6. `SELECT action, count(*) FROM audit_log WHERE action LIKE 'assistant.%' GROUP BY 1` shows `asked` equal to
   `answered`. No row holds text. `aslms assistant check` gives six zeros.
7. The documents of the Services section are updated: CLAUDE.md, the decisions log, Process Workflows 4.9, the
   regenerated software documentation with the 13.2 row and `TOC_PAGES` checked, `operations.md`, `schema.md` and
   `.env.example`.

## Open questions
None that block this item. The split by purpose, the three claim questions and the count first are the owner's
directions of 12 Nov 2026, and every other point is decided above.

**Owner checks at approval** (decided here and reversible; say if any should change):
1. **"Cases claimed by me" counts as My Cases shows them** (decision 6): cases the department still holds as primary
   owner where the officer made the claim or accepted the transfer. A watcher claim, and a case claimed and later
   transferred away, are not counted. The alternative is every claim the officer ever made, whatever happened since.
   That number would then match no screen.
2. **ASLMS writes the My Work answer, and the model only chooses the list** (decision 4). The earlier design had the
   model word the rows in a second call. That call is dropped: the count and the list come from the lists exactly.
3. **"My department has claimed" counts what the officer can see** (decision 6). A department or unit head sees the
   whole department. A dealing officer sees only what is assigned to them or to their unit, and the answer says "that
   you can see".
4. **Periods** (decisions 5 and 8). The claim questions count every period ("all") unless the question names one.
   "Week" means the last 7 days and "month" the last 30 days, counted in IST days.
5. **My Work is not offered in sourcetrace mode** (decision 13, unchanged from 27 Oct). When SourceTrace is connected
   the tab would disappear. Keeping it then, choosing by keywords only and sending nothing to SourceTrace, is a small
   later change; say so if wanted now.
6. **The "Ask in My Work" suggestion** in My Cases and All Court Orders (decision 11) is offered, never automatic.
7. **The case tab loses its scope switch** and gets an "Open the Assistant" link (decision 1). Switching tabs on the
   sidebar no longer asks the last question again (decision 2).
8. **My Work never answers "busy" or "starting"** (decision 8). When the model is loading, busy or down, the keyword
   table chooses the list at once.

## Deviations

Written by the developer during the build (14 Nov 2026), each the smallest choice where the note was silent.

1. **Migration number.** `0037_assistant_my_work.py`, `down_revision = "0036"` (row 257 `offices-import` took 0036).
   Row 209 `totp-authenticator` takes the next free number.
2. **`open` keeps its field name.** A My Work row's link is `{kind, href}` (the existing `AssistantOpenOut` shape), with
   `kind` `case_tab` (`/cases/<id>`) or the new `claim` (`/claim/recommended?department=<code>&case=<id>`); the note
   wrote `path`.
3. **Two more labels in `model_info`.** A work answer also stores `list_label` and `full_list_href`, so that
   `MessageOut.work` can show the list and its full-list link at every read without running the question again.
4. **Ranges.** "This week" is today to Sunday and "next week" Monday to Sunday of the next week (the portal's weeks run
   Monday to Sunday); `my_hearings` and `my_due_dates` default to `this_week` (the table named no default).
5. **The keyword table.** Decision 21 gave no phrase for `my_due_dates`: "due date(s)", "date(s) to confirm" and "next
   date(s) to confirm" were added at the specific rank, above the general "due" of `pending_actions`. "With me" and
   "my files" (`cases_with_me`) and "today" (`needs_attention`) sit at a third, most general rank, so "what is overdue
   with me?" is `pending_actions` with `when=overdue`. "Send" counts with "sent", "new orders" with "new order". Within
   `new_orders`, "today" gives 1 day and "month" or "30 days" 30 days.
6. **Count sentences the table left open.** `period=all` reads "Education has claimed n cases in all." and "Your
   departments have claimed n cases in all: …"; "that you can see" follows "cases" ("Education claimed 5 cases that
   you can see in the last 30 days."); a band reads "n cases are strongly (possibly) recommended to …"; `still_out` with
   a period reads "n files you sent in the last 30 days are still where you sent them."; one row reads "Showing it.";
   a sentence starting "at least" is capitalised.
7. **`needs_attention` counts the whole attention list.** `dashboard.personal_headline` is called with
   `list_size = WORK_SCAN_ROWS`, so "n things need your attention today" is not capped at the dashboard's 10.
8. **Names read by code.** The services give office codes for "sent by" and the departments; the adapter reads the
   office names from `offices` by code (reference data, no case data) for `sent_by.office_name` and the count
   sentences. Row fields `department` keep the code, which the portal shows through the kit `OfficeName`.
9. **Fields a service does not give stay empty.** `bench` is null on hearing rows (`calendar.my_calendar` returns no
   bench) and `parties` is filled only from case summaries (calendar, alert and dashboard rows carry case references
   without parties): nothing is added beyond what the screen's service returns (decision 5).
10. **`department_claimed`'s full-list link** goes to the first department whose membership has the Department tab
    (the whole department, `cases.view_all` or `custody.track`, as `inboxTabsFor`), else `/inbox/my-cases`.
11. **A service error other than a timeout** is stored as a `failed` answer, family `error`, with "Your lists could not
    be read because of an unexpected error; try again." (logged by class only).
12. **`suggest_work`** is stored (true or false) on every My Cases and All Court Orders answer in ollama and preview
    mode, whatever its outcome. A work answer's `engine` and `checks` are null, and the thread names who answered
    "Assistant (Your Lists)".
13. **Portal.** The page reads `?tab=` from the server page's `searchParams`; a tab press (and "Ask in My Work") uses
    the kit `Tabs`' `onSelect` with `router.replace`, so the tab shows at once; the page waits for the status before
    choosing a tab. "More Examples (n)" becomes "Fewer Examples" when open. One CSS rule (`.examples`) is new, so the
    layout signature (`layout-signature.json`) was regenerated. The uicheck state "/assistant (quick fact from the case
    record)" moved to `/assistant?tab=my-cases`, because My Work now opens first.
14. **Test names.** `test_scan_cap_says_at_least` uses `cases_with_me` (a scan with no row filter); the twelve keys of
    `test_each_work_question_equals_its_screen` run for an officer and a department admin.
15. **Software documentation.** `build.js` gains the chapter 6 paragraph, the 6.4 row, the extended 13.2 row and
    version 1.8; the document was regenerated, but `TOC_PAGES` could not be checked against a rendered copy on the
    build machine (no renderer installed): the scribe checks it.
16. **A failed status read (fix round).** The page chooses its tabs only from `GET /assistant/status`, so a failed
    read (an error answer or no network) shows the page heading and the kit's error banner with Try Again in place of
    the loading lines, which before stayed for ever; Try Again reads the status again and the tabs then open. The case
    tab needs no status to list its conversation and goes on without it. The uicheck fixture's court-answer thread now
    sends `work: null` (and `suggest_work: false`, `work: null` on its sources): the synthesiser filled the new
    optional `work` field, which made every court answer a My Work answer, so the four states waiting for `[S#]`
    markers, the Sources button and "From the Case Record" timed out.
