# Design: Session timeout (30 minutes idle with a 2-minute warning, 12-hour limit)

```
slug: session-timeout
status: awaiting-approval
author: architect
date: 2026-10-26
approved_by:
```

## Context
**Owner decision of 26 Oct 2026** (backlog row 169). The plan names no session rule; its only related lines are
"Login: individual user accounts with one-time password (OTP) verification" and "Logins … recorded" in the audit
log (section 5.13). So this is an owner addition, not a deviation from the plan. The rule:
- **Idle sign-out.** A person is signed out after **30 minutes without activity of their own**: clicks, typing,
  navigation. Background polling does not count. That covers System Health, Data Collection, the alert bell, the
  navigation counts and React Query refetches.
- **Warning.** A **2-minute warning** comes before the idle sign-out, with **Stay Signed In** and **Sign Out**. It
  works across the tabs of one browser: activity in one tab counts for all, and signing out in one tab signs out
  all of them.
- **Hard limit.** A session ends **12 hours after the sign-in that used the e-mailed code**, whatever the activity.
- **Enforced on the server.** A browser left open, or a stolen cookie, must not outlive these limits.

**What exists (checked in the code on main, 26 Oct 2026)**
- `core/config.py`: `aslms_access_token_minutes = 30` and `aslms_refresh_token_days = 14`.
- `api/security.py`:
  - `issue_access_token(user)` makes an HS256 JWT with `sub`, `typ`, `iat` and `exp`. It carries **no session
    identifier**.
  - `issue_refresh_token` writes a `refresh_tokens` row with `expires_at = now + 14 days`, tied to a device.
  - `revoke_refresh_token` (logout) sets `revoked_at = expires_at = now`, which marks the token as logged out.
- `services/auth.py::refresh` revokes the presented token and issues a new pair, with another full 14 days. A
  token presented again after rotation calls `end_sessions` for the whole login, writes `auth.refresh_reused` and
  answers `session_ended`. **So today a session never ends while any tab polls, and it lasts 14 days after the last
  poll.**
- `services/users.py::end_sessions` revokes every live refresh token of a login. It is called by:
  - `set_password` (own change, reset, administrator set);
  - an administrator's e-mail change;
  - disabling a login (`services/access.py`);
  - `sign_out_everywhere` (`aslms users sign-out`);
  - reuse detection.

  `revoke_device` revokes one device's tokens.
- `api/deps.py::current_user_pending` reads the access token, loads the user and refuses a token issued before
  `password_changed_at`. It reads no session.
- The portal's backend-for-frontend (`frontend/src/server/`):
  - `session.ts` keeps `aslms_at` (life `expires_in` − 30 s) and `aslms_rt` (life `ASLMS_REFRESH_TOKEN_DAYS`, so
    14 days) in httpOnly cookies;
  - `relay.ts` refreshes when `aslms_at` is missing, or once after an API 401, and answers `401 signed_out` when
    the refresh fails;
  - `refresh.ts` is single-flight.

  `lib/api/client.ts` sends every call with `X-ASLMS-Request: 1` and goes to `/login?next=…` on `signed_out`. The
  relay refuses `/auth/*`, so a new endpoint the browser calls must live outside `/auth`.
- Polling today:
  - `useInboxCounts` and `useMyCounts` every 2 min;
  - `useAlertCounts` every 2 min;
  - the System Health summary and token cards, the Data Collection progress and health screens;
  - React Query's refetch on window focus.

  None of these can be told apart from a person's request by the server today.
- The kit's `Dialog` in `components/ui/overlays.tsx`: footer with the secondary button on the left and one
  primary on the right. Its `firstFocus` gives focus to the first footer control when the body has no field.

**Not covered**
- Super-admin editing of the limits (decision 21).
- A list of open sessions on the profile page (the Devices list stays as it is).
- A limit on concurrent sessions.
- Wall-display or kiosk exceptions: the owner's rule applies to every login, so a System Health screen left open
  signs out too.

## Decisions

### A. Where the server holds a session
1. **A new table, `user_sessions`, has one row per sign-in.** The row is opened by `complete_login` (the
   e-mailed-code step) and holds:
   - `started_at`;
   - `expires_at` = `started_at` + 12 h, the hard limit, fixed at sign-in;
   - `last_activity_at`;
   - `ended_at` and `end_reason`.

   Every refresh token carries its `session_id`. Every access token carries the claim `sid`.
   Alternatives considered:
   - columns on `refresh_tokens` (an inherited `session_started_at` and a copied `last_activity_at`): every
     rotation would copy the state, and the per-request check would have to find "the current token" of a chain;
   - columns on `user_devices`: one browser can hold an old and a new sign-in at once;
   - a cache in Redis only: the state would be lost on a restart and could not be audited.

   One row per sign-in is the natural home, and the audit row of its end can point at it.
2. **The session starts at the code step and never at a refresh.** A refresh, a password change and the
   first-sign-in steps keep the same `session_id`, `started_at` and `expires_at`. So the 12 hours count from the
   e-mailed code, as the owner said. Only `complete_login` creates a row.
3. **A new sign-in from the same device replaces that device's open session.** `complete_login` ends the device's
   other open sessions with reason `replaced`. Otherwise the old chain, whose cookie the browser has just
   overwritten, would lapse 30 minutes later and be audited as an idle sign-out that never happened. `auth.login`
   is the record of the replacement, so no extra audit row is written.

### B. What counts as activity
4. **Activity reaches the server only as an explicit ping, `POST /me/activity`.** No other request moves
   `last_activity_at`: no GET, no mutation, no refresh. The browser sends the ping when the person acts (decision
   5). The server cannot tell a person's request from a poll, so it takes no request as activity on its own.
   Alternatives considered:
   - a header such as `X-ASLMS-Activity` on user-initiated requests: every call site would have to be classified,
     and one poll tagged by mistake keeps every session alive for ever. Typing a long note sends no request at all,
     so it would not count as activity;
   - counting every mutation: a mutation always follows a click that the ping already counts, so it adds nothing,
     and a stolen cookie could send mutations as easily as pings.
5. **The browser's own events define activity.** These count:
   - `pointerdown`, `keydown`, `wheel` and `touchstart` on the window (capture phase, passive);
   - a client-side route change and a full page load. These are the owner's "navigation", and opening a new tab
     is one.

   These do not count: `mousemove`, focus and visibility changes (returning to a tab is not an action), and any
   request the portal makes. Wheel and touch scrolling count because they are deliberate reading.

   **Known limit:** events inside an `<iframe>`, such as the browser's PDF viewer in the document view, do not
   reach the page. A person reading a PDF for 28 minutes without touching the page gets the warning.
6. **One ping a minute at most, with a trailing ping.** On activity:
   - the tab pings at once if the browser's last ping, which all tabs share, is 60 s old or older (leading edge);
   - if activity happens inside the 60 s window, one more ping goes at the end of the window (trailing edge).

   The server therefore always records activity at or after the person's real last activity, never before it.
   The server can be more lenient than the browser's clock by up to a minute, and never stricter (apart from a
   failed ping). **Stay Signed In** pings at once, with no throttle. The 60 s window is a constant in code, not a
   setting.

### C. Enforcement on the server
7. **Every authenticated request checks its session.** `current_user_pending` (and so `current_user`, `require`
   and `require_any`) reads the `sid` claim and loads the `user_sessions` row by its key. It refuses with 401:
   - **`session_limit`** when `now >= expires_at`, or when the row was ended with reason `limit`;
   - **`session_idle`** when `now >= last_activity_at + SESSION_IDLE_MINUTES`, or when the row was ended with
     reason `idle`;
   - the plain `token is not valid` it answers today when there is no `sid`, no row, a row of another login, or a
     row ended for any other reason.

   The refusal writes nothing: it is a computation on the row. The sweep (decision 12) writes the end. The check
   is one primary-key read added to the user read that is already made. The session id is put on
   `request.state.auth_session_id` for logout and the password change.
8. **The access token's life stays at 30 minutes, capped at the session's end.** The per-request check of
   decision 7 makes the session row, not the JWT, the authority. An access token that is still valid cannot act for
   an idle or expired session for even one request, so shortening it would add refreshes and protect nothing. Its
   `exp` is `min(now + 30 min, expires_at)`, so no token outlives its session on paper either.
   Alternative considered: a 5-minute access token with no per-request check. That leaves a window of up to 5
   minutes after the idle limit, and the owner's rule is exact.
9. **A refresh is refused once the session is idle or over its limit, and a refresh is not activity.**
   `auth.refresh` keeps its order:
   1. an unknown token: `refresh_invalid`;
   2. a revoked token: the existing reuse logic, unchanged;
   3. the session check of decision 7, which answers **401 `session_limit`** or **401 `session_idle`**, and
      `refresh_invalid` for a token without a session (one issued before migration 0028) or a session ended for
      another reason;
   4. the token's own expiry, the user and device checks, and the rotation as today.

   The new token carries the same `session_id`. Its `expires_at` is the session's `expires_at`, not `now + 14
   days`. `last_activity_at` is not touched.
10. **The 14-day refresh life is retired.** No refresh token can outlive a 12-hour session, so
    `ASLMS_REFRESH_TOKEN_DAYS` goes from the API settings, the web service's settings, `compose.yml` and
    `.env.example`. Settings ignore unknown variables (`extra="ignore"`), so an old `.env` line does no harm. The
    token answers (`/auth/otp/verify`, `/auth/refresh`, `/me/password`) gain `session_expires_in`, the seconds to
    `expires_at`. The web server sets the refresh cookie's `Max-Age` from it, so the cookie dies with the session.
    This supersedes portal-shell decision 3 ("`aslms_rt` 14 days") and the 14-day refresh life of otp-and-profile.
11. **Ending sessions follows the existing paths, and each path names its reason.**

    | Path | Session rows ended | `end_reason` | Audit row (unchanged unless new) |
    |---|---|---|---|
    | Logout (`POST /auth/logout`) | the caller's session | `signed_out` | `auth.logout` |
    | Idle lapse | that session (the sweep) | `idle` | **new** `auth.signed_out_idle` |
    | 12-hour limit | that session (the sweep) | `limit` | **new** `auth.session_limit` |
    | New sign-in on the same device | that device's other open sessions | `replaced` | `auth.login` |
    | `end_sessions`: own password change, reset, administrator password set, e-mail change, disable, `aslms users sign-out`, reuse detection | every open session of the login, except the caller's on an own password change (decision 13) | `ended` | the cause's row, as today |
    | `revoke_device` | that device's open sessions | `ended` | `auth.device_revoked` |

    The sweep **does not revoke refresh tokens**. Otherwise a lapsed session's token would look "rotated" when a
    stale tab presents it, and the reuse alarm would end the login's other sessions on other devices. The session
    check of decision 9 refuses that token with `session_idle` or `session_limit`. Reuse detection is otherwise
    unchanged.
12. **A sweep writes idle and limit ends, once each, at the moment the session lapsed.** `aslms.sessions_sweep`
    runs every 5 minutes and makes two conditional updates:
    - `UPDATE … SET ended_at = expires_at, end_reason = 'limit' WHERE ended_at IS NULL AND expires_at <= now
      RETURNING …`;
    - then `… SET ended_at = last_activity_at + idle, end_reason = 'idle' WHERE ended_at IS NULL AND
      last_activity_at + idle <= now RETURNING …`.

    It writes one audit row per returned row. The conditional `WHERE` guarantees exactly one row per session even
    with two sweeps running at once. The ping's own update (decision 14) is conditional too, so a ping cannot
    revive a session that the sweep is ending. A session whose browser was closed also ends here, so **every
    sign-in ends with exactly one of** `auth.logout`, `auth.signed_out_idle`, `auth.session_limit` or the row of the
    cause that ended it.
    Alternative considered: writing the end and the audit row in the request that is refused. That request rolls
    back on 401 (`get_session`), it would need a separate transaction, and a closed browser sends no request at
    all.
13. **An own password change keeps the caller's session.** `change_password` passes the caller's session id
    (`request.state.auth_session_id`) to `set_password`, and so to `end_sessions(…, keep=session_id)`. Every other
    session of the login ends, and the fresh pair joins the kept session with the same `started_at` and
    `expires_at`. Otherwise the first-sign-in password step would restart the 12-hour clock without a code. An
    administrator's set and a reset keep nothing.
14. **The ping refuses a session that has lapsed.** `POST /me/activity` runs `UPDATE user_sessions SET
    last_activity_at = now WHERE id = :sid AND ended_at IS NULL AND now < expires_at AND now < last_activity_at +
    idle`. If no row is updated, it answers 401 `session_idle` or `session_limit` (decision 7). A browser restored
    after a night away cannot revive its session by pinging on load.

### D. The portal
15. **The web server passes the two reasons through and clears the cookies.**
    - `relay.ts`: on an upstream 401 it reads `detail.code`. For `session_idle` or `session_limit` it **does not
      refresh**: it clears the session cookies (the device cookie stays) and answers 401 with the same code and
      message. A refresh that fails with either code is passed through the same way. Every other failure answers
      `signed_out` as today.
    - `handlers.ts`: `password()` does the same. `logout()` is unchanged: it ignores the API's answer and clears the
      cookies, so a Sign Out from an idle tab still works.
    - `session.ts::setTokens` sets the `aslms_rt` `Max-Age` from `session_expires_in` (12 h when the field is
      absent) and the `aslms_at` `Max-Age` from `min(expires_in, session_expires_in)` − 30 s.
    - `config.ts` drops `refreshTokenDays`.
16. **The browser keeps one shared clock in `localStorage`, and every tab reads it each second.** The keys:
    - `aslms.session.activity`, the last activity in milliseconds;
    - `aslms.session.ping`, the last ping;
    - `aslms.session.limits`, the `idle_seconds`, `warning_seconds` and hard end from the last ping answer;
    - `aslms.session.out`, `{reason, at}` written when any tab signs out.

    Each tab runs a 1-second tick that reads these keys and compares them with `Date.now()`. A `storage` listener
    reacts at once to another tab's write. The tick makes sleep and wake safe: a laptop opened after an hour signs
    out on the first tick, with no long `setTimeout` that may fire late. Throttled background tabs are also
    harmless, because the earliest tab to tick acts for all. When `localStorage` is not available (some private
    modes), the watcher keeps the same state in memory and works for one tab.
    Alternative considered: `BroadcastChannel`. It sends messages but keeps no state, so a newly opened tab would
    not know the last activity. A second mechanism for messages alone is not needed.
17. **The warning dialog.**
    - **When:** `components/shell/SessionWatch.tsx` opens a kit `Dialog` at `activity + idle − warning`, so 28:00
      by default.
    - **Title:** "Are You Still There?".
    - **Body:** "You will be signed out in 1:45 because there has been no activity for 28 minutes. Anything you have
      not saved will be lost." The countdown in m:ss updates each second. One polite live-region sentence is
      announced when the dialog opens, not every second.
    - **Footer:** **Sign Out** (secondary, left) and **Stay Signed In** (the one primary, right). Stay Signed In
      takes the focus: the kit's `firstFocus` honours a `data-autofocus` control first, which is a one-line kit
      addition. Without it, focus would land on Sign Out, and Enter would sign the person out.
    - **Stay Signed In,** the close button and Escape count as activity: they write the shared clock, ping at once
      and close the dialog in every tab.
    - **While the dialog is open,** the page's activity listeners are paused, so a stray scroll behind the overlay
      does not dismiss it silently. Activity in another tab (its Stay Signed In) closes it.
    - **Stacking:** the dialog is mounted last in the shell, so it is the innermost overlay above an open composer
      or modal, and only it answers Escape.

    Labels are Title Case under the label guard (`labelRules.ts`), and the body text is a sentence path.
18. **The 12-hour notice.** Two minutes before `expires_at`, the same component shows a notice instead.
    - **Title:** "Session Ending Soon".
    - **Body:** "Your session reaches its 12-hour limit in 1:45. Save your work now; you will then sign in again
      with a new code."
    - **Footer:** **Sign In Now** (secondary: signs out and goes to `/login?next=<here>`) and **Continue** (primary:
      closes the notice).

    Nothing can extend the hard limit, so there is no Stay Signed In. If both deadlines fall inside the window, the
    earlier one decides which dialog shows.
19. **At the deadline the tab signs out, and so do all the others.** At `activity + idle`, or at `expires_at`, the
    first tab to tick:
    1. writes `aslms.session.out` = `{reason: "idle" | "limit"}`;
    2. calls `/api/session/logout`, which clears the cookies (the API answers 401 on an idle session and that answer
       is ignored; the sweep writes the end);
    3. clears the React Query cache (the existing `clearCache` hook);
    4. goes to `/login?reason=idle&next=<here>` (or `reason=limit`).

    Other tabs see `out` and go to the same address without calling the API again. A **manual Sign Out** (the user
    menu or the dialog) writes `out` with reason `signed_out`, so every tab leaves at once. This is the owner's
    "signing out in one signs out all". `lib/api/client.ts::signedOut` takes the reason from the 401 code. It maps
    `session_idle` → `idle`, `session_limit` → `limit` and `signed_out` / `session_ended` → no reason, and writes
    `out` too. A poll that meets an expired session therefore also brings every tab to the sign-in page.
20. **The sign-in page explains, and unsaved work is not kept.**
    - **Message:** `/login` reads `reason` and shows an information banner above the form:
      - "You were signed out after 30 minutes without activity." (`idle`);
      - "Your session reached its 12-hour limit. Sign in again." (`limit`);
      - "You signed out." (`signed_out`, from another tab).

      The numbers come from `aslms.session.limits`; without them the text reads "after a period without activity".
      They are never taken from the address, so a crafted link cannot show false figures.
    - **Unsaved work:** nothing is saved for the person at sign-out. No draft note is saved to the server on their
      behalf, and no form text is kept in browser storage. An automatic save would be an act the person did not
      take, and text left in storage after sign-out would stay on a shared machine. Typing is activity, so losing
      text takes 30 minutes of no input, and the warning says what will be lost. `next` is kept, so the person
      returns to the same page after signing in.
    - **Where the watcher runs:** it is mounted in `PortalShell` and in the welcome layout (first-sign-in pages),
      not on the public pages.

### E. Settings and audit
21. **The limits are environment settings, not screen settings.**
    - `SESSION_IDLE_MINUTES`: default 30, 2–240;
    - `SESSION_WARNING_SECONDS`: default 120, 30–600, and less than the idle time;
    - `SESSION_MAX_HOURS`: default 12, 1–24.

    The API refuses to start on a bad combination, with a plain message. The browser learns the values from the
    ping answer and holds no copy. **No super-admin editing:** the owner did not ask for it, a security policy
    changed from a screen would need its own audit, confirmation and a floor, and a restart is acceptable for a
    rule that seldom changes. It can be a later item if wanted. The 60 s ping window and the 5-minute sweep are
    constants.
22. **Audit:**
    - `auth.signed_out_idle` and `auth.session_limit`, one per session end, written by the sweep with
      `Actor.system("sessions")`, entity `user` / the login's id (so they show on the user's audit trail). `after`
      holds `{session_id, device_id, started_at, last_activity_at, ended_at}` and `idle_minutes` or `max_hours`;
    - pings are **not** audited (up to one a minute, and not significant), so the session row is their record;
    - refusals (decision 7) are not audited, because the end is audited once by the sweep;
    - the Audit log screen groups the two new codes under "Sign-in and Password" by their `auth.` prefix, with no
      portal change.

    The plan's "Logins … recorded" is thereby completed by a recorded end for every sign-in.

## Data
Migration **0028** (planned; 0027 is row 154 `partial-code-match`, in flight). The developer takes the next free
number at build time and sets `down_revision` to match. The migration is hand-written. These are the schema.md
changes:

- **Group 1, new row after `user_devices`:**

  | `user_sessions` (derived) | id (uuid v7 PK; the access token's `sid`), user_id (→ users RESTRICT; logins are never deleted), device_id (→ user_devices RESTRICT, NOT NULL), started_at (timestamptz NOT NULL; the e-mailed-code sign-in), expires_at (timestamptz NOT NULL; started_at + `SESSION_MAX_HOURS`, fixed at sign-in), last_activity_at (timestamptz NOT NULL; moved only by `POST /me/activity`), ended_at (timestamptz NULL), end_reason (`session_end_reason`: `signed_out` / `idle` / `limit` / `replaced` / `ended`, NULL), created_at, updated_at | One row per sign-in (design `session-timeout`, migration 0028). CHECKs `ck_user_sessions_times` (expires_at > started_at AND last_activity_at >= started_at), `ck_user_sessions_ended` ((ended_at IS NULL) = (end_reason IS NULL)). Indexes `ix_user_sessions_user_id`, `ix_user_sessions_device_id`, partial `ix_user_sessions_open` (last_activity_at) WHERE ended_at IS NULL (the sweep). Idle ends are written at `last_activity_at + SESSION_IDLE_MINUTES` and limit ends at `expires_at` by the 5-minute sweep, each with one audit row (`auth.signed_out_idle`, `auth.session_limit`). Every authenticated request checks its row. Written only by `services/sessions.py` and `services/auth.py`; never deleted (`aslms_app` SELECT / INSERT / UPDATE). `updated_at` trigger. |

  `session_end_reason` is a native enum (a machine state, DB_STANDARD §7), created with the `pg_enum` helper of
  `db/base.py`. The table is not on the CASCADE list, so both FKs are RESTRICT.
- **Group 1, `refresh_tokens`:** add `session_id (→ user_sessions RESTRICT, NULL for tokens issued before 0028;
  index ix_refresh_tokens_session_id)`. The notes become: "Rotating refresh tokens within one sign-in session:
  each rotation keeps `session_id`, and `expires_at` is the session's `expires_at` (no longer 14 days). Access
  tokens are 30-minute JWTs carrying `sid`, never past the session's end. A token without a session is refused.
  Presenting a rotated token again revokes every refresh token of the login (`otp-and-profile`, decision 10)." The
  FK is RESTRICT because `user_sessions` is not on the CASCADE list. `refresh_tokens` keeps its own CASCADE to
  `users`, which does not run, since logins are never deleted.
- **Conventions:** no change to the CASCADE list.

Migration steps, upgrade, in one transaction:
1. Create the enum `session_end_reason`.
2. Create `user_sessions` with the CHECKs, indexes, `COMMENT ON TABLE … 'class=derived'` and the `updated_at`
   trigger.
3. Grants, as for `user_devices` in 0010: ALL to `aslms_owner`, SELECT to `aslms_readonly`, and SELECT, INSERT,
   UPDATE to `aslms_app`.
4. Add `refresh_tokens.session_id` with its FK and index.

No data step: tokens issued before 0028 have no session and are refused (decision 9), so **everyone signs in once
after the deploy**. No audit row is written for the migration (no reference data changes).

Downgrade: drop the column, the table and the enum. The session history goes with them; the table is derived and
the audit rows stay. An access token with `sid` is still readable by the old code, which ignores the claim.

## Services
- **`services/sessions.py` (new):**
  - `open_session(session, user, device, now) -> UserSession`: ends the device's other open sessions (`replaced`)
    and opens a new one with `expires_at = now + max_hours` and `last_activity_at = now`;
  - `check(row, user_id, now, settings) -> None`: raises `SessionIdle` or `SessionLimit` (both `AuthFailure`,
    401), or `SessionInvalid` for no row, the wrong login or another end reason;
  - `touch(session, sid, now, settings) -> UserSession`: the conditional update of decision 14, raising as `check`
    does;
  - `end(session, rows_or_filter, reason, now)`, used by logout, `end_sessions` and `revoke_device`;
  - `sweep(session, settings, now) -> {"limit": n, "idle": m}`: decision 12, with the audit rows;
  - `state(row, now, settings) -> dict`: the ping answer of the API section.
- **`api/security.py`:**
  - `issue_access_token(user, settings, session_row)` adds `sid` and caps `exp` at `expires_at`;
  - `read_access_claims` returns `(user_id, iat, sid | None)`;
  - `issue_refresh_token(…, session_row)` writes `session_id` and `expires_at = session_row.expires_at`;
  - the 14-day arithmetic is removed;
  - `revoke_refresh_token` also ends the token's session with reason `signed_out`.
- **`services/auth.py`:**
  - `complete_login` calls `open_session` after `_touch_device`;
  - `_signed` takes the session row;
  - `refresh` applies decision 9;
  - `change_password(…, auth_session_id)` follows decision 13;
  - `revoke_device` ends the device's sessions;
  - `sign_out_everywhere` and the reuse path end sessions through `end_sessions`;
  - `Signed` gains `session_expires_in`.
- **`services/users.py`:** `end_sessions(session, user, at=None, keep=None)` also ends the login's open
  `user_sessions` (`ended`), except `keep`. `set_password(…, keep_session=None)` passes it on. The count returned
  stays the refresh-token count, which the existing audit rows record.
- **`api/deps.py::current_user_pending`:** decision 7, raising `HTTPException(401, {"code": …, "message": …})` for
  the two reasons, with `WWW-Authenticate: Bearer`.
- **`core/config.py`:** `session_idle_minutes`, `session_warning_seconds` and `session_max_hours`, with the
  validator of decision 21. `aslms_refresh_token_days` is removed.
- **`jobs/celery_app.py`:** the beat entry `sessions-sweep` → `aslms.sessions_sweep` at `crontab(minute="1-59/5")`,
  following the pattern of `aslms.napix_log_purge`.
- **CLI:** `aslms sessions sweep [--dry-run]` prints the counts, for the integrator and the runbook.
  `aslms users sign-out` is unchanged in use and now also ends sessions.
- **Audit:** decision 22. No event, no notification and no e-mail.

## API
- **`POST /me/activity`.** Function: **none, any signed-in login** (`current_user_pending`, like `GET /me`, so the
  first-sign-in pages can ping too). No body. 200:
  `{idle_seconds: int, warning_seconds: int, idle_ends_in: int, session_ends_in: int}`, all in seconds, where
  `idle_ends_in` equals `idle_seconds` just after the touch. 401 `session_idle` or `session_limit` once lapsed
  (decision 14). It is relayed by the web server as `/api/backend/me/activity`, since it is not under `/auth` and
  returns no token. It touches only the caller's own session, so no visibility question arises.
- **Every authenticated endpoint** can now answer 401 `{"detail": {"code": "session_idle" | "session_limit",
  "message": …}}` (decision 7). No endpoint's `Permission` changes.
- **`POST /auth/refresh`** (no function; it takes the refresh token) adds 401 `session_idle` and `session_limit`.
- **`POST /auth/otp/verify`, `/auth/refresh` and `POST /me/password`:** `TokenOut` gains `session_expires_in: int`.
  `token-routes.json` is unchanged (same routes).
- **`POST /auth/logout`** (any signed-in login) also ends the session.
- `frontend/openapi.json` and `lib/api/schema.d.ts` are regenerated.

Web server (`frontend/src/server/`): decision 15. Portal:
- `lib/session/clock.ts`: pure deadline and phase functions and the throttle rule;
- `lib/session/store.ts`: the `localStorage` keys, the storage listener and the in-memory fallback;
- `components/shell/SessionWatch.tsx`: the hook, both dialogs and the activity listeners, mounted in `PortalShell`
  and `app/(welcome)/layout.tsx`;
- `lib/api/client.ts::signedOut(reason)` (decision 19);
- the `/login` banner (decision 20);
- `firstFocus` honours `data-autofocus`;
- texts in `messages.ts` under `T.session` and `T.login`.

## Jobs
`aslms.sessions_sweep`: a beat task every 5 minutes (minute 1, 6, 11 and so on). It runs no queue item, makes no
NAPIX call and writes only `user_sessions` and `audit_log`. It is idempotent: a second run in the same minute ends
nothing.

## Tests
Backend database tests (`backend/tests/db/`). They sign in through `auth_support.sign_in`. A new helper,
`auth_support.age_session(api, email, minutes=…, field=…)`, moves `last_activity_at`, or `started_at` and
`expires_at`, back on the test clock.
- `test_sign_in_opens_a_session`: one row; `expires_at` is `started_at` + 12 h; `last_activity_at = started_at`;
  the refresh token's `session_id` and the access token's `sid` match the row; the access token's `exp` is no later
  than `expires_at`.
- `test_request_refused_when_idle`: `last_activity_at` aged 31 min, then `GET /me` answers 401 `session_idle`.
  Aged 29 min, it answers 200.
- `test_request_refused_past_hard_limit`: `expires_at` in the past answers 401 `session_limit`, even right after a
  ping.
- `test_polling_does_not_extend`: GETs of `/alerts/counts`, `/inbox/mine/counts` and `/admin/system-health` over a
  moving test clock leave `last_activity_at` unchanged, and the session lapses on time.
- `test_refresh_does_not_extend_and_keeps_the_session`: same `session_id`; token `expires_at` = session
  `expires_at`; `last_activity_at` unchanged.
- `test_activity_extends`: `POST /me/activity` moves `last_activity_at` to now; the answer's four fields; a GET
  after 25 more minutes is 200.
- `test_activity_cannot_revive_an_idle_or_expired_session`: 401 with the right code, and the row is unchanged.
- `test_refresh_refused_when_idle` and `..._past_limit`: 401 `session_idle` or `session_limit`; no new token
  written.
- `test_token_without_session_refused`: a refresh token with `session_id` NULL answers `refresh_invalid`, and an
  access token without `sid` answers 401.
- `test_reuse_detection_unaffected`: a rotated token presented again answers `session_ended`, every session of the
  login ends `ended`, and one `auth.refresh_reused` row is written.
- `test_logout_ends_the_session_signed_out`.
- `test_change_password_keeps_the_caller_session_and_ends_others`: same `started_at` and `expires_at`; the
  login's other device's session ends `ended`.
- `test_new_sign_in_on_the_same_device_replaces_the_open_session`: `replaced`, with no idle audit later.
- `test_session_ends_with_device_revoke_disable_email_change_reset_and_sign_out_everywhere` (parametrised).
- `test_sweep_ends_idle_and_limit_once`: `ended_at` is the lapse moment; one audit row each with the `after`
  fields of decision 22 and the system actor; a second sweep writes nothing; an active session is untouched.
- `test_swept_session_token_gives_session_idle_not_reuse`: after the sweep, the old refresh token answers
  `session_idle`, and the login's session on another device stays open (no reuse alarm).
- `test_ping_and_sweep_race`: a ping whose conditional update finds the row ended answers 401.
- `test_migration_0028`: up, down, up on the test database; tables, enum, grants (`aslms_app` cannot DELETE from
  `user_sessions`) and the class comment. `test_migrations.py`: round trip and an empty `compare_metadata`.

Backend unit tests (`backend/tests/unit/`):
- `test_session_settings_validation`: ranges, warning ≥ idle refused, defaults 30 / 120 / 12;
- `test_access_claims_carry_sid_and_cap_exp`;
- `test_compose_web.py`: `ASLMS_REFRESH_TOKEN_DAYS` no longer passed to `web`.

Web server (vitest, `src/server/`):
- `session.test.ts`: the refresh cookie `Max-Age` equals `session_expires_in`, the access cookie is capped by it,
  and the fallback when the field is absent;
- `relay.test.ts`: an upstream 401 `session_idle` or `session_limit` clears the cookies, passes the code and calls
  no refresh; a refresh failing with those codes passes them through; any other refresh failure is still
  `signed_out`;
- `handlers` (`password`): the same mapping.

Portal (vitest, fake timers):
- `clock.test.ts`: the deadline and phase table (active, warn-idle, warn-limit, expired-idle, expired-limit, and
  the earlier deadline wins); the throttle sends a leading ping, then one trailing ping, then nothing while
  quiet.
- `SessionWatch.test.tsx`:
  - the warning at 28:00 with the countdown, and Stay Signed In focused;
  - Stay Signed In pings at once and closes;
  - at 30:00 it calls logout, clears the cache and goes to `/login?reason=idle&next=…`;
  - `api()` calls and React Query refetches do not move the clock;
  - a `storage` event with newer activity closes the open warning;
  - an `out` event navigates without a logout call;
  - a 31-minute jump of `Date.now()` with no ticks signs out on the next tick (sleep and wake);
  - the 12-hour notice and its two buttons;
  - the in-memory fallback when `localStorage` throws;
  - listeners are paused while the dialog is open.
- `client.test.ts`: 401 `session_idle` or `session_limit` writes `out` and navigates with the reason.
- `login` page: each reason shows its banner, the numbers come from storage and not from the address, and an
  unknown reason shows nothing.
- `labels.test.ts` and the wording guard pass with the new texts.

uicheck (`frontend/e2e`):
- the fixtures answer `POST /api/backend/me/activity` with the defaults (1800 / 120 / 43200);
- two new interaction states:
  - "Session Warning": `idle_seconds` 125 and `warning_seconds` 120, so the dialog "Are You Still There?" opens
    within about 5 s;
  - "Session Ending Soon": `session_ends_in` 125;
- both at 375, 768 and 1280 px.

## Verification
1. `ruff check` clean, `pytest -q` green, frontend `npm test` green, and the uicheck run with its two new states.
2. Owner step after the merge: apply 0028 with the `migrate` step, then rebuild with `docker compose build`.
   Everyone signs in once (decision 9 and "Data").
3. Owner's browser check at http://localhost:3000, with `SESSION_IDLE_MINUTES=3` and
   `SESSION_WARNING_SECONDS=60` set in `.env` for the run (then removed):
   1. Sign in, open a second tab on the System Health screen, and leave both alone. At 2:00 both tabs show "Are
      You Still There?".
   2. Click Stay Signed In in one tab. Both dialogs close.
   3. Leave both again. At 3:00 both tabs are on the sign-in page with "You were signed out after 3 minutes
      without activity.", even though System Health kept polling.
   4. Sign in, then click Sign Out in one tab. The other tab leaves at once.
   5. Copy the `aslms_rt` and `aslms_at` cookie values before an idle sign-out. Replaying them with `curl`
      against `http://localhost:3000/api/backend/me` after the lapse answers 401 `session_idle`.
4. Hard limit: in a signed-in session, set the row's `expires_at` to two and a half minutes ahead with SQL as the
   owner role. "Session Ending Soon" appears, and the session then ends with "Your session reached its 12-hour
   limit."
5. Within 5 minutes of each end: `SELECT end_reason, ended_at FROM user_sessions ORDER BY started_at DESC LIMIT 3`
   shows `idle`, `signed_out` and `limit`. `GET /audit?action=auth.` lists one `auth.signed_out_idle` and one
   `auth.session_limit` row. `aslms sessions sweep --dry-run` then reports 0 and 0.

## Open questions
None. Each choice the owner did not state is decided above, with its reason:
- the 12-hour notice and its buttons (decision 18);
- scrolling counts as activity and focus does not (decision 5);
- no automatic saving of unsent text (decision 20);
- the limits as environment settings, not screen settings (decision 21);
- one audit row per idle or limit end (decision 22).

A different answer at approval changes only the decision named.
