# Design: OTP and profile — e-mailed sign-in codes, password reset, new devices, first-sign-in confirmation

```
slug: otp-and-profile
status: approved
author: architect
date: 2026-10-07
approved_by: product owner (nayan.semt@gmail.com) on 2026-10-07
```

## Context
Plan §8.1: "Login: individual user accounts with one-time password (OTP) verification." Backlog row 7: OTP
sign-in and password reset by e-mail, new-device OTP, profile confirmation on first login, notification
preferences.

In place today:
- `POST /auth/login` checks e-mail and password (argon2id) and returns tokens at once (30-minute HS256 access
  JWT, rotating 14-day refresh token stored hashed in `refresh_tokens`); `/auth/refresh`, `/auth/logout`, `/me`
  (API slice of 3 Oct 2026). No OTP is asked.
- Tables from migration 0001 not used yet: `otp_codes` (purpose `login` / `password_reset` / `new_device`,
  `code_hash`, `expires_at`, `attempts`, `consumed_at`); `users.must_confirm_profile` (set `true` by every
  creation path: `create_user`, the seeded super admin, the first department admin, new heads) and
  `refresh_tokens.device_label`.
- Mail: `services/mailer.py` (Mailtrap API, SMTP, console, `RecordingMailer` for tests), chosen by
  `MAIL_BACKEND`. The console backend never logs a body.
- Notification preferences: built by `alerts-notifications` (decision 17; `GET` / `PUT
  /me/notification-preferences`, audited). That design records that this row's "notification preferences" is
  covered there; this item only shows them in the first-sign-in confirmation.
- Passwords are set by an administrator (`POST /admin/users`, `POST /admin/users/{id}/password`,
  `aslms users set-password`); offices-admin left "set your own password on first sign-in" to this item.
- Lessons from the 26–27 Sep build (read only, nothing copied): OTP attempt counters and token revocations were
  silently rolled back with the failing request until they were committed before the error; the owner chose
  a server-enforced two-minute resend wait, a cap of 10 codes an hour, and a password-reset request that
  answers the same whether or not the account exists.

Not covered: SMS codes (no gateway; plan Phase 2, row 27); single sign-on; the portal screens and the
httpOnly cookie handling (`portal-shell`, row 11); per-IP throttling at the reverse proxy (`deployment-checklist`,
row 16); retention / pruning of old `otp_codes` and `refresh_tokens` rows (deployment checklist).

## Decisions

> **Owner review 2026-10-07 (binding over the text below):** a code is required at **every** sign-in; a known
> device never skips it. Build no device-trust mechanism: drop the `AUTH_DEVICE_TRUST_DAYS` setting and the
> "trusted device returns tokens directly" path of decision 16 and its tests (keep the device record, the
> new-device notice e-mail and `/me/devices`). The mobile number is mandatory at profile confirmation
> (`^[6-9][0-9]{9}$`).

1. **Sign-in is two steps: password, then a 6-digit code e-mailed to the login's address.** Step one checks
   e-mail and password; step two takes the challenge id and the code and returns the tokens. Alternatives: a
   code without a password (passwordless) — weaker against a compromised mailbox and not what "verification"
   reads as; TOTP authenticator apps — not available to every officer. Whether a known device may skip step
   two is **open question 1**; the design carries both answers through one setting
   (`AUTH_DEVICE_TRUST_DAYS`, decision 6) so the only thing pending is its value.
2. **Codes.** Six digits from `secrets.randbelow`, stored as HMAC-SHA256 keyed with `ASLMS_JWT_SECRET` (a
   leaked table cannot be brute-forced offline without the secret; a plain SHA-256 of a 6-digit code can),
   compared in constant time. Valid `OTP_TTL_MINUTES` (10, as `schema.md`); at most `OTP_MAX_ATTEMPTS` (5)
   tries, then the code is spent. One live code per login and purpose: issuing a new one consumes the older
   ones. The code is never logged, never put in an audit row, never returned by the API.
3. **Send limits (owner's choice of 27 Sep kept).** A new code for the same login and purpose at most every
   `OTP_RESEND_SECONDS` (120; 429 with `retry_after`), at most `OTP_MAX_PER_HOUR` (10) codes per login across
   purposes. Resend issues a new challenge and ends the old one.
4. **Account lock against guessing.** `LOGIN_MAX_FAILURES` (10) failed passwords or codes for one login within
   `LOGIN_LOCK_MINUTES` (15) refuse further sign-in and reset steps for that login with 429 `locked` and
   `retry_after` until the window passes; counted from the login's `auth.login_failed` and `auth.otp_failed`
   audit rows (no new counter column). Unknown e-mails are not counted (no row to count); per-IP limits belong
   to the reverse proxy. Alternative: a permanent lock needing an admin — rejected, it lets anyone lock an
   officer out before a hearing.
5. **Failures are committed, not rolled back.** The request transaction rolls back on an exception
   (`api/deps.get_session`), so the sign-in routes return their 401 / 429 as a response object instead of
   raising: the attempt counter, the spent code, the audit row and any revocation are committed with it. A
   test proves each survives.
6. **Devices.** The client keeps a device token (random, 32 bytes, issued by the server after the first
   successful code from that client, stored hashed in the new `user_devices`; the portal will hold it in an
   httpOnly cookie). Each sign-in names its device; refresh tokens are tied to it. On a device the login has
   never verified from, after the code the user receives a "new sign-in to ASLMS" e-mail (time, browser label,
   masked IP; a mail failure is logged, never blocks the sign-in) and an `auth.new_device` audit row is
   written. A user lists their devices and signs one out (`/me/devices`). `AUTH_DEVICE_TRUST_DAYS`: when 0,
   every sign-in asks a code (purpose `login`); when N > 0, a device that passed a code within N days signs in
   with the password alone and any other device is asked a code (purpose `new_device`). **The value is open
   question 1** (0 is the plan's literal reading).
7. **Password reset by e-mail.** `POST /auth/password-reset/request` with an e-mail always answers 202 with a
   challenge id and the same timings; for an unknown or disabled login, or inside the resend wait, no mail is
   sent and the id never verifies (no account disclosure, no inbox flooding). `…/confirm` with the code and a
   new password sets it, revokes every refresh token and device trust of the login, clears
   `must_change_password`, and does not sign in (the user signs in again). The super admin may reset their own
   password this way (it is the same mailbox; replacement stays CLI-only).
8. **Password rules.** At least 10 characters (as today) with at least one letter and one digit, not equal to
   the current password; no periodic expiry. Applied to every path that sets a password (admin, CLI, reset,
   change, first sign-in). Alternative: a complexity score library — not needed at this scale.
9. **Credentials change ends other sessions.** A reset, a self-change, an administrator's reset, an e-mail
   change (decision 13) and disabling a login set `users.password_changed_at` (or, for disable, revoke tokens)
   and revoke the login's refresh tokens; `current_user` refuses an access token issued before
   `password_changed_at` (whole seconds), so an old 30-minute token stops at once. A self-change returns a fresh
   token pair for the caller's device.
10. **Refresh-token reuse is treated as theft.** Presenting an already-rotated refresh token revokes every
    refresh token of that login (committed, decision 5) and writes `auth.refresh_reused`; the user signs in
    again. Lesson of the earlier build.
11. **First sign-in: own password, then profile confirmation, enforced on the server.** A login created or reset
    by someone else has `must_change_password = true` (new column); every created login keeps
    `must_confirm_profile = true`. While either is set, `current_user` refuses every endpoint with 403
    `password_change_required` or `profile_confirmation_required`, except: `GET /me`, `GET /me/profile`,
    `POST /me/password`, `POST /me/profile/confirm`, `GET` / `PUT /me/notification-preferences`,
    `POST /auth/logout`, `/auth/refresh`. Order: password first (confirm answers 409
    `password_change_required`), then the profile. Alternative: let the portal enforce the order — refused by
    the rule that the server enforces access.
12. **What the user confirms.** Shown: e-mail (read only — it is the sign-in and code address), full name
    (editable), mobile (editable), each active membership with office, designation and user type (read only —
    authority belongs to the administrators; a wrong designation is corrected by them), and the notification
    preferences (editable through the existing service). Confirmation sets `profile_confirmed_at`, clears
    `must_confirm_profile`, audits `profile.confirmed` with before / after. Later edits of name and mobile go
    through `PATCH /me/profile` (`profile.updated`). Whether the mobile number is mandatory is **open
    question 2** (it is unverified until an SMS gateway exists).
13. **Administrators can correct a login's e-mail.** With OTP, a wrong e-mail locks the person out for good;
    today nothing can change it. `PATCH /admin/users/{id}` gains `email` under the existing login-level rule
    (`users.edit`; super admin, or a caller whose scope covers the primary membership's office; the super
    admin's own login only from the CLI): unique, lower-cased, audited `user.email_changed` (old and new, masked
    in the mail only), ends sessions and device trust (decision 9), and mails a notice to the old address.
14. **Administrator resets force a change.** `POST /admin/users/{id}/password` and `aslms users set-password`
    set `must_change_password = true`; `aslms users create-super-admin` and the seed already create with
    `must_confirm_profile = true` and now also `must_change_password = true` (the `.env` password is a
    bootstrap secret).
15. **Mail is required for sign-in.** The OTP mail goes out synchronously through `get_mailer` (an
    `app.state.mailer` override in tests, like the scanner). A send failure answers 502 `mail_failed` with no
    secret in the message and leaves no live code. With the console backend (nothing configured) and
    `APP_ENV=prod` the API answers 503 `mail_not_configured`; in dev the console backend gives no code either
    (it never logs bodies), so development uses the Mailtrap sandbox URL. No bypass switch exists.
16. **`POST /auth/login` changes shape** (no portal consumes it yet): it returns `{step: "otp", challenge…}`,
    or the tokens directly only when decision 6 trusts the device. Tests sign in through one helper that reads
    the code from the `RecordingMailer` (see Tests).
17. **Audit.** Rows: `auth.login_failed` (known login only; `after = {reason: password | inactive}`),
    `auth.otp_sent` (`after = {purpose, sent_to: masked}`), `auth.otp_failed` (`{purpose, attempts}`),
    `auth.locked`, `auth.login`, `auth.new_device`, `auth.refresh_reused`, `auth.logout`,
    `auth.password_reset_requested` (known login only), `auth.password_reset`, `auth.password_changed`,
    `auth.device_revoked`, `profile.confirmed`, `profile.updated`, `user.email_changed`, `user.set_password`
    (now with `{must_change: true}`). Unknown-e-mail attempts are logged at INFO with a masked address only.

## Data
Migration **0010_otp_profile** (new; 0001–0009 untouched). `schema.md` Group 1 updated before it is written.

`users` (master) — three columns added:
> `password_changed_at` timestamptz NULL (set by every password set and by an e-mail change; access tokens
> issued before it are refused), `must_change_password` boolean NOT NULL default false (set when anyone other
> than the person sets the password; cleared by the person's own change or reset), `profile_confirmed_at`
> timestamptz NULL (first confirmation; `must_confirm_profile` false afterwards). Back-fill:
> `must_change_password = must_confirm_profile` for existing rows. Audit columns unchanged
> (`created_by`, `updated_by`, `updated_at`).

`user_devices` (derived) — new table:
> id (uuid v7 PK), user_id (→ users RESTRICT; logins are never deleted), token_hash (char 64, unique; SHA-256 of
> the device token), label (text ≤ 200, the client's name for itself, NULL), user_agent (≤ 400), first_ip,
> last_ip (inet as text ≤ 64, valid addresses only), first_seen_at, last_seen_at, verified_at (last successful
> code from this device), revoked_at (NULL), created_at, updated_at. Index `ix_user_devices_user_id`. CHECK
> `ck_user_devices_seen` (last_seen_at >= first_seen_at). Written only by `services/auth.py`; never deleted
> (`aslms_app` SELECT / INSERT / UPDATE); a revoked device stays as a record. `updated_at` trigger
> (`MUTABLE_TABLES`). Design `otp-and-profile` decision 6.

`refresh_tokens` (derived) — one column:
> `device_id` (→ user_devices RESTRICT, NULL for tokens issued before 0010), index `ix_refresh_tokens_device_id`.

`otp_codes` (derived) — one index, no column:
> `ix_otp_codes_user_purpose_created` (user_id, purpose, created_at) for the resend wait and hourly cap. The
> `id` is the challenge id. `consumed_at` is set on success, on the last failed attempt, and when a newer code
> of the same purpose is issued.

No `ref_*` code and no enum value added (`otp_purpose` already has the three purposes). No new `Permission`.
Downgrade: drops the table, the columns and the index; refuses (raises) if any `user_devices` row exists, so a
populated database is not silently stripped.

## Services
- `services/passwords.py` (new): `check_policy(new, current_hash=None)` (decision 8), `hash_password`,
  `verify_password` moved here from `services/users.py` (re-exported there); `set_password` in `users.py`
  calls it and takes `by_self: bool` (sets `must_change_password = not by_self`, `password_changed_at`,
  revokes refresh tokens).
- `services/otp.py` (new): `issue(session, user, purpose, mailer, *, cooldown) -> OtpCode` (limits of
  decision 3, consume older codes, HMAC hash, mail with subject "ASLMS sign-in code" / "ASLMS password reset
  code" stating purpose and minutes, never logging the body; `MailError` → `OtpMailFailed`);
  `verify(session, challenge_id, code, purpose) -> VerifyResult` (ok, user, attempts_left, reason
  `invalid` / `expired` / `spent`; never raises on a wrong code, decision 5); `seconds_until_resend`;
  `mask_email`.
- `services/auth.py` (new): `start_login(session, email, password, device_token, label, ip, ua, mailer) ->
  LoginStep` (lock check, timing-safe password check with the existing dummy hash, device lookup, trust rule,
  code issue); `complete_login(session, challenge_id, code, device_token, label, ip, ua, mailer) -> Signed`
  (verify, create or refresh the device, new-device notice, `last_login_at`, tokens via `api/security.py`);
  `resend(session, challenge_id, mailer)`; `request_reset(session, email, mailer) -> challenge id` (always one);
  `confirm_reset(session, challenge_id, code, new_password)`; `change_password(session, actor, user, current,
  new, device)`; `refresh(session, raw)` with reuse detection (decision 10); `devices(session, user)`;
  `revoke_device(session, actor, user, device_id)`; `is_locked(session, user) -> int seconds`.
- `services/profile.py` (new): `get_profile(session, user)`, `confirm(session, actor, user, full_name, mobile,
  preferences=None)` (409 if `must_change_password`; preferences through `notifications.set_preferences`),
  `update(session, actor, user, full_name?, mobile?)`; mobile normalised and validated (`+91` optional, 10
  digits starting 6–9).
- `services/users.py`: `update_profile` gains `email` (decision 13) with uniqueness, the notice to the old
  address and session end; `create_user` sets `must_change_password = True`.
- `api/security.py`: `issue_refresh_token(..., device_id)`; `consume_refresh_token` moves its logic to
  `auth.refresh`; access tokens unchanged in shape.
- `api/deps.py`: `current_user` refuses tokens older than `password_changed_at` and applies the gate of
  decision 11; new `current_user_pending` (no gate) for the allowed endpoints; `get_mailer(request)` with the
  `app.state.mailer` override.
- `core/config.py` and `.env.example`: `OTP_TTL_MINUTES=10`, `OTP_MAX_ATTEMPTS=5`, `OTP_RESEND_SECONDS=120`,
  `OTP_MAX_PER_HOUR=10`, `LOGIN_MAX_FAILURES=10`, `LOGIN_LOCK_MINUTES=15`, `AUTH_DEVICE_TRUST_DAYS` (value per
  open question 1).
- CLI: `aslms users set-password` sets `must_change_password`; `aslms users sign-out --email` revokes every
  refresh token and device of a login (audited as the `.env` super admin).

## API
All errors carry `{code, message}`; 429 adds `retry_after`. "Public" = no token; "signed in" = any valid token,
no `Permission` (own login only, as `/me/notification-preferences`). Nothing here reads cases, so the case
visibility rule does not apply; every endpoint acts only on the caller's own login except the admin one.

| Method and path | Function | Request | Response | Notes |
|---|---|---|---|---|
| `POST /auth/login` | public | `{email, password, device_token?, device_label?}` | `{step: "otp", challenge_id, purpose, sent_to (masked), expires_in, resend_after}` or, on a trusted device, `{step: "done", …TokenOut}` | 401 `invalid_credentials` (one message for wrong e-mail, wrong password, disabled), 429 `locked`, 429 `too_many_codes`, 502 `mail_failed`, 503 `mail_not_configured`. |
| `POST /auth/otp/verify` | public | `{challenge_id, code (6 digits), device_token?, device_label?}` | `TokenOut` + `device_token` (when new) + `next_step` (`ready` / `change_password` / `confirm_profile`) | 401 `otp_invalid` with `attempts_left`, 401 `otp_expired` (expired or spent), 429 `locked`. Purposes `login` and `new_device` only. |
| `POST /auth/otp/resend` | public | `{challenge_id}` | as the login `step: "otp"` answer, new `challenge_id` | 429 `retry_after` inside the wait for sign-in; for a reset challenge the same neutral 202 answer as the request. |
| `POST /auth/password-reset/request` | public | `{email}` | 202 `{challenge_id, expires_in, resend_after}` always | Decision 7. |
| `POST /auth/password-reset/confirm` | public | `{challenge_id, code, new_password}` | 204 | 401 as verify; 422 `weak_password`. |
| `POST /auth/refresh` | public | `{refresh_token}` | `TokenOut` + `next_step` | 401 `refresh_invalid`; reuse → 401 `session_ended` (decision 10). |
| `POST /auth/logout` | signed in (gate exempt) | `{refresh_token}` | 204 | As today. |
| `GET /me` | signed in (gate exempt) | — | as today + `must_change_password`, `profile_confirmed_at` | |
| `POST /me/password` | signed in (gate exempt) | `{current_password, new_password, device_token?}` | `TokenOut` (fresh pair) | 401 `wrong_password` (counted as a failure, decision 4), 422 `weak_password`. |
| `GET /me/profile` | signed in (gate exempt) | — | `{email, full_name, mobile, memberships[{office, designation, role, is_primary}], must_change_password, must_confirm_profile, profile_confirmed_at, notification_preferences}` | |
| `POST /me/profile/confirm` | signed in (gate exempt) | `{full_name, mobile?, notification_preferences?}` | profile | 409 `password_change_required`; 422 `invalid_mobile`; 409 `already_confirmed`. |
| `PATCH /me/profile` | signed in | `{full_name?, mobile?}` | profile | Audited when something changed. |
| `GET /me/devices` | signed in | — | `[{id, label, user_agent, first_seen_at, last_seen_at, verified_at, trusted_until, current, revoked_at}]` | Own devices only. |
| `POST /me/devices/{id}/revoke` | signed in | — | 204 | Revokes the device and its refresh tokens; 404 for another login's device. |
| `GET` / `PUT /me/notification-preferences` | signed in (gate exempt) | as built | as built | Unchanged (alerts-notifications). |
| `PATCH /admin/users/{id}` | `users.edit` (as built) | as built + `email?` | `UserOut` | Decision 13; 409 `email_taken`; super admin's login 403 `super_admin_cli_only`. |
| `POST /admin/users/{id}/password` | `users.reset_password` (as built) | as built | 204 | Now sets `must_change_password` and ends sessions; 422 `weak_password`. |

## Jobs
None. Codes are sent synchronously in the request; the new-device and e-mail-change notices too (failure
logged, not retried).

## Tests
Unit (`tests/unit/test_auth_rules.py`): code format and HMAC check; `mask_email`; password policy (length,
letter, digit, same as current); mobile normalisation; the trust rule for `AUTH_DEVICE_TRUST_DAYS` 0 and N;
the access-token age check at whole seconds.

Database (`tests/db/test_auth_otp.py`, `test_profile.py`, `test_api_auth.py`), with a `RecordingMailer` on
`app.state.mailer`:
- sign-in: password then code gives tokens; wrong password and unknown e-mail give the same 401 and body; a
  disabled login 401; no token is issued by step one when the trust days are 0.
- codes: expired → `otp_expired`; fifth wrong code spends it; **the attempt counter and the spent code survive
  the 401** (read back in a new session); a resend inside 120 s → 429 with `retry_after`; the eleventh code in
  an hour → 429; a resend ends the previous code; the mail body holds the code and no log record does
  (`caplog`).
- lock: ten failures in 15 minutes → 429 `locked` even with the right password; open again after the window
  (clock moved).
- mail failure → 502 `mail_failed`, no live code left; console backend with `APP_ENV=prod` → 503.
- devices: first verify issues a device token and sends the new-device notice; a second sign-in from it sends
  none; with trust days N the trusted device signs in with the password alone and an unknown device gets a
  `new_device` code; a revoked device is unknown again and its refresh tokens fail.
- reset: unknown e-mail, disabled login and a repeat inside the wait answer identically (status, keys) and send
  nothing; confirm sets the password, revokes all refresh tokens, clears `must_change_password`, and the old
  access token is refused.
- refresh reuse revokes every refresh token of the login and the revocation survives the 401.
- gate: a new login gets 403 `password_change_required` on `/cases`, 200 on `/me`; after `POST /me/password`
  403 `profile_confirmation_required`; confirm before the password → 409; after confirm `/cases` answers as
  the type allows; preferences in confirm are saved and audited.
- admin: password reset sets `must_change_password` and ends sessions; e-mail change by the department admin
  in scope works, out of scope 403, duplicate 409, the old address gets the notice, the super admin's login
  403; weak password from the admin 422.
- audit: each action of decision 17 writes its row; no row contains a code, a password or a token.
- migration: 0010 up, down (empty `user_devices`), up; down refuses with a device row.

Existing API tests: the 22 `POST /auth/login` call sites move to one helper `tests/db/auth_support.py::sign_in(api,
email, password)` (login, read the code from the recording mailer, verify); fixture factories create logins
with `must_change_password = False, must_confirm_profile = False` unless a test is about the first sign-in.
`test_login_me_refresh_logout` is rewritten for the two steps.

## Verification
1. `ruff check` clean; `pytest -q` green.
2. Compose up with the Mailtrap sandbox URL and token in `.env`; `alembic upgrade head` reaches 0010.
3. `aslms users create` a test officer; `POST /auth/login` → `step: "otp"`; the code arrives in the Mailtrap
   sandbox inbox; `POST /auth/otp/verify` → tokens with `next_step: "change_password"`; `GET /cases` → 403
   `password_change_required`; `POST /me/password`; `POST /me/profile/confirm`; `GET /cases` → 200.
4. Sign in again from the same device token: no new-device mail; from no token: a new-device mail.
5. `POST /auth/password-reset/request` for an unknown e-mail and for the officer: identical answers, one mail.
6. `docker compose logs api` contains no 6-digit code, password or token (grep for the codes just used).
7. `SELECT action, count(*) FROM audit_log WHERE action LIKE 'auth.%' OR action LIKE 'profile.%' GROUP BY 1`
   shows the rows of the steps above.

## Open questions
None. The owner answered both on 2026-10-07:
1. **A code at every sign-in** (option a, as the plan reads): password plus e-mailed code every time, and a notice
   e-mail when a new device signs in. `AUTH_DEVICE_TRUST_DAYS` is fixed at 0 and is not offered as a setting in
   this item; a known device never skips the code.
2. **The mobile number is mandatory** at profile confirmation, Indian 10-digit format (`^[6-9][0-9]{9}$`, stored
   without the country code). It is not verified until an SMS gateway exists (backlog row 27).

## Deviations
Recorded by the developer while building (7 Oct 2026); none changes a business rule.
1. **No device trust (owner's review).** No `AUTH_DEVICE_TRUST_DAYS`; `POST /auth/login` always answers
   `step: "otp"` with purpose `login`; `/me/devices` has no `trusted_until`. The `new_device` purpose stays in the
   enum and `verify` accepts it, but nothing issues it.
2. **`current` in `/me/devices`** is the device named by an optional `X-Device-Token` request header (access tokens
   keep their shape, so the server cannot tell the device from the token alone); without the header every
   `current` is false.
3. **Reset confirm answers every failed code alike**: wrong, expired, spent and unknown challenges all give 401
   `otp_invalid` without `attempts_left`, so a reset challenge for an unknown e-mail cannot be told from a real one
   (decision 7 over the "401 as verify" of the API table). Sign-in verify keeps `otp_invalid` with `attempts_left`
   and `otp_expired` (its challenges exist only after a correct password).
4. **Reset request stays neutral**: while the login is locked, or when the reset mail fails, the request answers the
   same 202 and sends nothing (logged), instead of 429 / 502, so the answer never discloses an account.
   `503 mail_not_configured` is server-wide and is kept. Reset confirm while locked answers 429 `locked` as designed.
5. **A failed send leaves no row**: the unsent `otp_codes` row is removed (the older codes stay consumed), so a mail
   outage costs no resend wait and does not count towards the hourly cap.
6. **Sign-in resend** is allowed for a live challenge or one spent by wrong codes; a challenge already used or
   superseded answers 401 `otp_expired` (a used challenge must never yield a code without the password).
7. **Reuse detection**: a presented refresh token counts as reused when it was revoked after the login's last
   password set and its device is live. Tokens ended by a password set or e-mail change (revoked at
   `password_changed_at`), by signing a device out, or by disabling the login answer plain `refresh_invalid`.
8. **Audit details**: the CLI sign-out writes `auth.signed_out` (`{tokens_revoked, devices_revoked}`); a wrong
   current password at `POST /me/password` writes `auth.login_failed` with `{reason: password, step:
   change_password}`; `auth.password_reset_requested` carries `{sent, reason}` (`inactive`, `locked`, `wait`,
   `mail_failed`); `auth.new_device` has entity type `user_device` with `user_id` in `after`.
9. **Out-of-scope e-mail change answers 404**, not 403: `PATCH /admin/users/{id}` already answers 404 for a login the
   caller cannot see, and that rule is kept.
10. **A reset revokes refresh tokens, not devices** (there is no device trust to revoke); devices stay known, so the
    next sign-in from them sends no new-device notice.
11. **A logged-out refresh token is not reuse**: `POST /auth/logout` revokes the token and sets its `expires_at` to
    the same instant, with no schema change. `refresh` treats a revoked token with `expires_at <= revoked_at` as
    logged out and answers plain `refresh_invalid` without ending the login's other sessions; only a rotated
    token (`expires_at > revoked_at`) counts as reuse under decision 10.
11. **`UserError` lives in `services/passwords.py`** (re-exported by `services/users.py`) so `WeakPassword` is a
    `UserError` and every existing refusal path also refuses a weak password; the API maps it to 422
    `weak_password`. `PasswordIn.password` accepts any length so the policy, not the schema, answers.
12. **The seeded super admin's `.env` password must pass the policy** (10+ characters, a letter and a digit), since the
    seed creates it through `create_user`; an existing super admin is untouched.
13. **Tests**: the session fixture and the migration tests wipe the test database before going down (0010's
    downgrade refuses while `user_devices` rows exist); test passwords gained a digit; `auth_support.sign_in`
    ages the login's earlier codes when a test signs the same login in twice inside the resend wait.
14. **A change of password or e-mail spends every live code of the login** (`users.end_codes`, every purpose, in
    the same transaction as `end_sessions`): a sign-in challenge begun with the old password, or a sign-in or
    reset code mailed to the old address, answers 401 afterwards. A reset confirmation is unaffected (its own code
    is spent by the check before the password is set).
15. **Refusals that are returned (and therefore committed) never half-apply**: `PATCH /me/profile` checks name
    and mobile before assigning either; `notifications.set_preferences` checks every field before it touches the
    row, so a refused `POST /me/profile/confirm` leaves the preferences as they were.
16. **Logout revokes only the caller's own refresh token**; another login's token is treated as not found (still
    204, the `auth.logout` row is written for the caller).
17. **Sign-in resend is narrower than deviation 6** (review of 8 Oct 2026). A challenge is resent only while
    (a) it is live or was spent by wrong codes, (b) it has not expired, (c) it is the newest code of its purpose for the
    login, and (d) it was created after the login's `password_changed_at`, which a password set, a reset or an e-mail
    change moves. Any other challenge answers 401 `otp_expired`. A challenge spent by codes therefore stops
    yielding codes once the credentials change (decision 9, deviation 14). An old challenge id cannot be replayed
    after its resend. A live code that has expired means signing in again.
18. **Sign-in steps of one login are serialised by row locks**, with no schema change. Every step that reads or
    writes the lock counter or a code first takes `SELECT ... FOR UPDATE` on the login's `users` row
    (`otp.lock_user`): password step, code verify, resend, reset request and confirm, own password change, and `otp.issue`.
    `otp.verify` then locks the `otp_codes` row. The lock order is always `users` first, then `otp_codes`. Parallel
    requests therefore get at most 5 tries per code and at most 10 failures per lock window. They cannot leave two live
    codes for one purpose or redeem one code twice. Requests for one login wait for each other, and requests for
    different logins do not.
