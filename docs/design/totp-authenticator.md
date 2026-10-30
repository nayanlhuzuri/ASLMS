# Design: Authenticator App — an optional sign-in method that replaces the e-mailed code once switched on

```
slug: totp-authenticator
status: awaiting-approval
author: architect
date: 2026-10-30
approved_by: (pending)
```

## Context
Backlog row 209 (backend) and row 210 (portal), added by the orchestrator. On 30 Oct 2026 the owner decided to add an
authenticator app (TOTP, RFC 6238) as a sign-in method. The owner revised the rule twice that day. The final words
are:
- "keep the new authenticator as an added functionality. the user for the first time can enable it and upon enabling
  will always go for the authenticator instead of the email otp";
- on required types: "if they enable it, only then it will be required";
- on switching it off: "yes and this will be for everyone".

So:
- **Optional for every login**, the Super Administrator and Department Administrators included. There is no required
  type, no enrolment gate and no "required types" setting.
- **Once switched on, always the app.** That login's code step asks only for the authenticator code. The e-mailed code
  is neither offered nor accepted for it, and there is no "E-mail Me a Code Instead".
- **Logins that have not switched it on** keep today's e-mailed code, unchanged.
- **Anyone may switch it off themselves**, only while signed in and only after entering a current authenticator code.
  It is audited and a notice is mailed, and the login returns to the e-mailed code.
- **One recovery code** per login with the app, shown on screen once, rotated after use. **Lost phone:** the Super
  Administrator resets another login's app only on a ticket; the Super Administrator's own app is reset only from the
  server's command line. With no e-mail fallback, these are the only ways back.
- **Second-factor methods as a provision:** e-mail and authenticator now. SMS is not built and not enabled (no SMS
  charges), but the method layer lets it be added later as one connector.
- Any authenticator app (SHA-1, 6 digits, 30 s); advice to switch off cloud backup of codes; QR made locally; no
  warning e-mail after wrong codes; no passkeys now.

Plan §8.1: "Login: individual user accounts with one-time password (OTP) verification." An authenticator code is a
one-time password too, so this follows the plan; it is **not a deviation**. The plan's SMS mentions concern alerts
(Phase 2), not sign-in.

This design **changes** `otp-and-profile` decision 1, which set TOTP aside as "not available to every officer". It is
now an option each person may take up, and nobody is made to. The decisions log records the change in the build
commit.

In place today (read in the code, 30 Oct 2026):
- `services/auth.py`:
  - `start_login`: lock, password check, then `otp.issue(..., OtpPurpose.LOGIN, ...)`, which e-mails a 6-digit code at
    every sign-in (owner's ruling of 7 Oct 2026, no device trust);
  - `complete_login`: `otp.verify`, device, `sessions.open_session`, tokens;
  - `resend`, `request_reset` / `confirm_reset`, `change_password`, `refresh`.
  - The lock (`is_locked`) counts `auth.login_failed` and `auth.otp_failed` audit rows: 10 in 15 minutes. Failures
    are raised after their writes are flushed and returned by the router, so they commit. Every step first locks the
    login's `users` row (`otp.lock_user`).
- `services/otp.py`: HMAC-SHA256 code hashes keyed with `ASLMS_JWT_SECRET`, 10 minutes, 5 tries, a 2-minute resend
  wait and 10 codes an hour. The code goes into no log, no audit row and no API answer.
- `api/deps.py`: `current_user` (the first-sign-in gate) and `current_user_pending`. This item adds no gate.
- `user_devices`, `user_sessions` (30-minute idle and 12-hour limits, row 169) and the new-device notice. Unchanged
  apart from one column on `user_sessions`.
- Admin tickets (`services/tickets.py`, `/admin/tickets/*`): the registry `KINDS` has one kind, `head_change`.
  - A department admin's request opens a ticket for the Super Administrator.
  - The Super Administrator's own request is applied at once and recorded as an approved ticket.
  - Alerts go to the Super Administrator when a ticket opens and to the proposer when it is decided.
- `services/preflight.py` checks secrets by name and never prints values.
- Dependencies: `cryptography` and `argon2-cffi` are already dependencies; there is no TOTP or QR library.
- The portal's CSP has `img-src 'self' data:`.
- Nothing in the database is encrypted at rest. `aslms_readonly` and the backups see every table.

Not covered:
- **SMS codes.** They need an SMS gateway connector (row 27), verified mobile numbers (row 34) and DLT registration;
  none of these is built here.
- **Passkeys and security keys** (WebAuthn): a possible later row.
- **Single sign-on.**
- **A warning e-mail after wrong codes:** none (owner).

## Decisions

1. **The app is an option each login switches on, and then it is the only code (owner).**
   - **Switching on:** My Profile → Authenticator App → Set Up. Enrolment is confirmed with a first code (decision 6).
   - **After that:** the login's sign-in code step asks only for the authenticator code. The e-mailed code is not
     offered and not accepted, and there is no switch at the code step.
   - **A login without the app:** sign-in is exactly as today.
   - **Nobody is required:** no type is required, there is no enrolment gate, and `current_user` is unchanged.
   Alternatives: the app required for chosen types (the brief's option b), withdrawn by the owner ("only if they
   enable it"); a choice of method at each sign-in, also withdrawn by the owner, since it would add no protection
   against someone with the password and the mailbox.
2. **A method layer for the second step (owner's provision).**
   - **Registry:** `services/second_factor.py` holds `METHODS` keyed by code, one handler per method, in the same
     pattern as the ticket `KINDS`.
   - **Handler:** `code`, `label`, `sends_code` (whether a code leaves the server), `optional` (a method a person
     switches on), `start(session, user, challenge, mailer, settings)` (sends the code, or nothing for the app) and
     `check(session, user, challenge, code, settings) -> CheckResult`.
   - **Built:** `email` (wraps today's `otp.issue` / `otp.verify`; the base method) and `totp` (`services/totp.py`;
     optional).
   - **Records:** each challenge records its method (`otp_codes.method`); each session records the proof that opened
     it (`user_sessions.signed_in_with`).
   - **One question:** sign-in, password reset and the profile all ask `methods.method_for(user)`. The answer is
     `totp` while the login has an active authenticator, otherwise `email`.
   - **A third method:** one handler plus one reference row, with no change to sign-in, reset or enrolment.
   Alternatives: an `if totp … else email` branch, reworked when SMS comes; a plugin system, too much for two methods.
3. **SMS: a planned method, shown as Not Available in Administration only (owner's provision).**
   - **In the registry:** `PLANNED = {"sms": Planned(label="Text Message (SMS)", needs=[...])}`, with no handler and
     no reference row.
   - **On the Sign-In Security page:** greyed, with the badge Not Available and the sentence "Needs an SMS gateway
     connection (row 27), verified mobile numbers (row 34) and DLT registration of the sender and message templates."
     It has no switch.
   - **In the API:** the setting refuses `sms` with 422 `method_not_available`.
   - **Elsewhere:** the sign-in pages and My Profile never mention it.
   Reason: the Super Administrator sees that the provision exists and what it takes, but cannot switch on something
   that would leave people unable to sign in. Hiding it would hide the provision; a switch would offer something that
   cannot work.
   **Enabling SMS later** takes:
   - the gateway connector in `backend/aslms/integration/sms/` (row 27);
   - verified mobile numbers (row 34);
   - DLT registration;
   - a `SecondFactor.SMS` member with its `ref_second_factor` row;
   - an `SmsMethod` handler that sends a hashed code as `email` does.
   The `otp_codes` CHECK already treats every method except `totp` as one that sends a hashed code.
4. **The portal setting: Sign-In Security (owner's provision).**
   - **What it holds:** one versioned row, `auth_settings`, with `methods_enabled`: the optional methods people may
     switch on. Default `{totp}`.
   - **E-mail:** the base method. It is always on, because it is the sign-in method of every login without the app
     and the channel of password resets and notices. The page shows it with the badge Always On and no switch.
   - **Who edits it:** only the Super Administrator, on the new Administration page Sign-In Security, with a reason,
     audited `auth.settings_changed` (before and after). The function is the new reserved `admin.sign_in_security`:
     enabled for no type and never overridden, like `admin.tickets`, so only the Super Administrator holds it.
   - **Switching an optional method off stops new set-ups only.** Logins already using it keep it until they switch
     it off or are reset, so nobody is locked out and "always the app once switched on" holds. Setup then answers 409
     `method_disabled`, and the page shows how many logins still use the method.
   - **Empty table:** means the default. The seed writes version 1.
   Alternatives: `.env` settings, refused because the owner wants it in the portal; refusing to switch off a method
   while logins use it, which would make the switch useless once one person has the app; dropping existing
   authenticators when switched off, which would break the "always the app" rule silently.
5. **The code step of sign-in.**
   - **Password step:** `start_login` keeps its password and lock checks, then opens a challenge through
     `method_for(user)`.
   - **E-mail:** today's mailed code.
   - **App:** an `otp_codes` row with `method = 'totp'` and no code hash. Nothing is sent, and the row does not count
     toward the resend wait or the hourly cap, which count only rows that sent a code.
   - **Challenge limits:** today's 10-minute validity and 5 tries.
   - **Answer:** `POST /auth/login` adds `method` and `recovery_allowed`; `sent_to` is NULL and `resend_after` 0 for
     `totp`.
   - **Resend:** `POST /auth/otp/resend` on a `totp` challenge answers 409 `nothing_to_resend`.
   - **Code check:** `complete_login` checks the code through the challenge's method. A wrong code writes
     `auth.otp_failed` `{purpose, method, attempts}`, counted toward the lock as today. A success writes `auth.login`
     `{device_id, new_device, method, drift}`, where `drift` (−1, 0, +1) is the matched step (decision 9).
   - **No e-mail way in:** there is no endpoint that turns an app challenge into an e-mailed one.
6. **Setting the app up (enrolment).**
   - **Start:** `POST /me/authenticator/setup` creates a `pending` authenticator with a new 160-bit secret (RFC 4226
     §4), encrypted (decision 10).
   - **Returned once**, with `Cache-Control: no-store`: the `otpauth://` URI, the key as text in groups of four, and a
     QR code as an SVG `data:` URI.
   - **Pending limits:** the setup lives `AUTH_TOTP_SETUP_MINUTES` (15) and takes 5 confirmation tries. A new setup
     ends the older pending one (`abandoned`, secret wiped). At most `AUTH_TOTP_SETUPS_PER_HOUR` (5) setups an hour.
   - **Confirm:** `POST /me/authenticator/confirm` `{setup_id, code}` checks a first code (window and replay,
     decision 9). On success:
     - the authenticator becomes `active`; an older active one, if this was a replacement, ends as `replaced`;
     - the recovery code is issued (decision 11) and returned once;
     - every live e-mailed sign-in code of the login is spent (`users.end_codes` for the sign-in purposes), so no
       e-mailed code issued before enrolment can still complete a sign-in;
     - from the next sign-in the login uses the app only.
   - **Audit and notice:** `auth.authenticator_setup_started`, `auth.authenticator_enrolled` and
     `auth.recovery_code_issued`; a notice "authenticator app switched on" is mailed.
   - **Wrong confirmation codes:** they write `auth.authenticator_setup_failed` and do **not** count toward the
     sign-in lock. The person is signed in and already holds the secret, so guessing gains nothing; the 5 tries per
     setup bound them.
   - **The secret is never shown again:** `GET /me/authenticator` returns state only.
   - **Current session:** setting the app up keeps it and the devices.
   - **Screen advice:** the screen says that, once confirmed, every sign-in will need the app and that the recovery
     code is the way back after a lost phone.
7. **Any app, standard parameters (owner).**
   - **URI:** `otpauth://totp/ASLMS:<e-mail>?secret=<BASE32>&issuer=ASLMS&algorithm=SHA1&digits=6&period=30`. These
     are the parameters every app supports; they are constants in code and stored per row only as a record (CHECKed
     to those values).
   - **Issuer:** `AUTH_TOTP_ISSUER` (default `ASLMS`; no agency names).
   - **Screen wording:** the enrolment screen names no particular app ("any authenticator app") and advises: "Switch
     off cloud backup or sync of codes in the app if it offers one, so your codes stay only on your phone."
8. **QR code made on the server, with no online service (owner).**
   - **Library:** `segno` (pure Python, no dependencies, BSD licence), pinned `>=1.6,<2`.
   - **Output:** an SVG returned as a `data:image/svg+xml;base64,` URI, which the existing CSP `img-src 'self' data:`
     allows.
   - **Model guard:** `segno` holds no model or runtime, so the `no_local_model` guard is unaffected.
   Alternatives: a browser QR library, which adds a frontend dependency while the secret comes from the server
   anyway; an online QR service, forbidden.
9. **Code checking, window and replay.**
   - **Computation:** TOTP with the standard library (`hmac`, `hashlib`, `struct`) per RFC 6238 / 4226; no `pyotp`.
     The RFC vectors are the unit test.
   - **Window:** a code is accepted for steps t−1, t and t+1 (±30 s), each candidate compared in constant time.
   - **Replay:** the accepted step must be greater than `user_authenticators.last_used_step`. That column is set on
     every accepted code: sign-in, confirmation, replacement, switching off, a new recovery code and password reset.
     It is set under the login's `users` row lock, then a lock on the authenticator row.
   - **So:** each code is used once. A second sign-in within the same 30 s answers `otp_invalid` with "This code was
     already used; wait for the next one."
   - **Clock:** the server clock must be synchronised. A new runbook section covers NTP on the host. `drift` in
     `auth.login` makes a drifting clock visible.
10. **The secret is encrypted with a new key from `.env` only.**
    - **Cipher:** AES-256-GCM (`cryptography`).
    - **Key:** `ASLMS_TOTP_KEY`, 32 random bytes in URL-safe base64. It is separate from `ASLMS_JWT_SECRET`, and
      preflight refuses equal values.
    - **Stored columns:** `secret_ciphertext`, `secret_nonce` (12 random bytes per encryption) and `key_fingerprint`
      (the first 8 hex characters of HMAC-SHA256(key, "aslms-totp-key-id")).
    - **Associated data:** `aslms-totp:<authenticator id>`, so a ciphertext cannot be moved to another row.
    - **Rotation:** the optional `ASLMS_TOTP_KEY_PREVIOUS` is used for decryption only. `aslms ops totp-rekey`
      re-encrypts every live row under the current key (dry run by default, `--apply`).
    - **When an authenticator ends:** its ciphertext, nonce and fingerprint become NULL. The row stays as history; the
      secret does not.
    - **Where the secret appears:** only in the setup answer. It is never in a log, an audit row, an error or a `repr`
      (a `Secret` wrapper with a masked `__repr__`).
    - **Backups and the read-only role:** they see ciphertext only. The key is not in the backups.
    - **If the key is lost:** every login with the app is unable to sign in until it is reset (tickets; the command
      line for the Super Administrator). The runbook therefore requires a sealed offline copy of `ASLMS_TOTP_KEY`.
    - **Missing or invalid key:** an error in preflight with `APP_ENV=prod`, a warning otherwise. The API starts;
      setup and app-code checks answer 503 `authenticator_unavailable`.
    Alternatives: encrypting with the JWT secret, where rotating one would destroy the other; `pgcrypto`, where the
    key would travel in SQL and could reach statement logs.
11. **The recovery code: one per login with the app, rotated on use (owner).**
    - **Format:** 20 characters of Crockford base32 (100 bits), shown as `XXXXX-XXXXX-XXXXX-XXXXX`.
    - **Input:** normalised. Case, dashes and spaces are ignored; I and L read as 1, O as 0.
    - **Storage:** argon2id, the existing password hasher. It is independent of the TOTP key, so a key rotation keeps
      it valid.
    - **Display:** on screen once, at enrolment, with Copy and "I Have Saved It". It is never e-mailed, logged or
      audited.
    - **Use:** `POST /auth/recovery/verify` `{challenge_id, recovery_code}`, on the app challenge of a login with a
      live recovery code.
      - **Wrong code:** adds an attempt to the challenge and writes `auth.otp_failed` `{method: "recovery"}`, counted
        toward the lock.
      - **Right code:** spends it; opens the session with `signed_in_with = recovery_code`; issues a new code and
        returns it in that one answer; writes `auth.recovery_code_used` and `auth.recovery_code_issued`; mails a
        notice "your recovery code was used" that carries no code. This is a notice of use, not of wrong codes, so
        the owner's "no warning e-mail after wrong codes" is kept.
    - **New code on demand:** `POST /me/authenticator/recovery-code` `{code}` (a current app code) issues a new one
      and spends the old.
    - **End:** a recovery code ends with its authenticator.
12. **Replacing the app (a new phone).**
    - **Call:** `POST /me/authenticator/setup` while an authenticator is active.
    - **Needs one of:** `current_code`, a code from the current app (a wrong one writes `auth.otp_failed`
      `{purpose: "replace"}`, counted); or a session opened by a recovery code. Otherwise it answers 409
      `already_enrolled`.
    - **Until confirmed:** the old authenticator stays active until the new one is confirmed, then ends as `replaced`.
    - **So:** a person who lost the phone but kept the recovery code recovers alone: sign in with the recovery code,
      then set up the new phone. This is the person's own app, so it does not touch the rule that only the Super
      Administrator resets **another** login's app.
13. **Switching the app off: anyone, signed in, with a current code (owner).**
    - **Call:** `POST /me/authenticator/remove` `{code}`, for every login including the Super Administrator.
    - **Needs:** a current app code (window and replay rules). A wrong code writes `auth.otp_failed`
      `{purpose: "remove"}`, counted.
    - **No password, no recovery code** stands in: the owner's rule is "after entering a current authenticator code".
      A person without the phone replaces the app by the recovery code (decision 12) or asks for a reset (decision 14).
    - **Effect:** the authenticator ends as `removed`, its recovery code ends, `auth.authenticator_removed` is written,
      and a notice "authenticator app switched off" is mailed. The next sign-in uses the e-mailed code.
    - **Session:** the current session and the devices are kept.
14. **Lost phone: reset by the Super Administrator on a ticket (owner).**
    - **The kind:** a new ticket kind, `authenticator_reset` ("Authenticator App Reset"), in the existing mechanism.
    - **Who raises it:**
      - (a) a holder of `users.reset_password` whose scope covers the login, by the existing `login_scope_member`
        rule. Today that means the department administrator, for the delegable types.
      - (b) the person, from a session still open (My Profile → Request a Reset).
      - (c) the Super Administrator directly. As for `head_change`, this is applied at once and recorded as an
        approved ticket. It is the path for logins nobody else may raise for: department heads, Department
        Administrators, State-tier logins, and anyone who telephones or writes to the Super Administrator.
    - **Payload:** `{user_id, reason}`. The reason (10–500 characters) is required; no documents are taken.
    - **Open ticket:** one open ticket per login (partial unique index).
    - **On opening:** the Super Administrator gets the usual `admin_ticket` alert. The person gets a notice e-mail ("a
      reset of your authenticator app was requested by …; if you did not ask for it, tell your administrator"), a
      guard against a reset obtained by deception.
    - **Approval needs a decision remark** (the Super Administrator's reason; required for this kind). It re-checks
      that the app is still active (`ticket_stale` otherwise), then:
      - ends the authenticator as `reset_by_ticket` with the ticket id, and ends its recovery code;
      - ends every session of the login (`users.end_sessions`; an open access token stops at its next request);
      - mails a notice;
      - writes `auth.authenticator_reset` `{ticket_ref, by: "ticket", reason, sessions_ended}`.
      The person then signs in with an e-mailed code and may set the app up again.
    - **Refused:** naming the Super Administrator's login (403 `super_admin_cli_only`).
    - **Visibility:** the requester also sees the tickets they raised (a clause added to `visible_condition`).
    - **Department:** `department_id` is the target's primary-membership department, NULL for a State-tier login. The
      `ref_no` is allocated on that code, or on the State root code `GOA` when it is NULL.
    Alternatives: a department admin resets directly, which the owner ruled out (the Super Administrator only); a
    request from the sign-in page without signing in, which would be an unauthenticated way into the Super
    Administrator's queue and an account-existence oracle.
15. **The Super Administrator's own app: command line only (owner).**
    - **Command:** `aslms users reset-authenticator --email <e-mail> --reason "<text>"`.
    - **Scope:** it acts only on the Super Administrator's login. Any other login is refused with "raise an
      Authenticator App Reset ticket".
    - **Effect:** as an approval (`reset_by_cli`), audited `auth.authenticator_reset` `{by: "cli"}` as the Super
      Administrator's login, like the other user commands.
    - **No API route.**
16. **Password reset goes through the method layer, with the proof sign-in needs.**
    - **Request:** unchanged. It e-mails a code for every login and stays neutral (no account disclosure).
    - **A login without the app:** the e-mailed code alone, as today.
    - **A login with the app:** `…/confirm` also needs `authenticator_code`. The e-mailed code is checked first. If
      the login has the app and no app code was given, the answer is 409 `authenticator_code_required`; the e-mailed
      code stays usable and no failure is counted. Enrolment is disclosed only to someone who holds the mailed code.
      A wrong app code writes `auth.otp_failed` `{purpose: "password_reset", method: "totp"}` and adds an attempt to
      the reset challenge.
    - **An app code alone is never accepted:** a stolen phone must never stand in for the mailbox (phone plus new
      password would take the account).
    - **Recovery code: not accepted in a reset.** Someone who has forgotten the password **and** lost the phone uses
      the ticket, then resets by e-mail. This keeps one recovery flow, and it always ends in a session.
    Reason for asking the app at all: without it, the mailbox alone could change the password of a login that chose
    the app and end its sessions.
17. **Devices, sessions and the lock otherwise unchanged.**
    - **As built:** devices, the new-device notice, the 30-minute and 12-hour limits, refresh rotation and
      `/me/devices`.
    - **New record:** `user_sessions.signed_in_with` records the proof that opened the session.
    - **Sessions:** a reset ends them; setting up, replacing or switching off the app keeps them.
    - **The lock:** still 10 counted failures in 15 minutes across all methods, audited `auth.otp_failed` with the
      method. No warning e-mail after wrong codes.
18. **Notices are mailed; secrets never are.**
    - **Notices:** switched on, switched off, reset (with the ticket number or "from the server"), reset requested,
      recovery code used.
    - **Mail failure:** logged with a masked address and never blocks, like the new-device notice.
    - **Never in a mail:** a secret, a key, a code or a recovery code.
19. **Wording.**
    - **Title Case** (the `titleCase` helper and its guards): Authenticator App, Set Up Authenticator App, Enter the
      Code From Your Authenticator App, Use a Recovery Code, Save Your Recovery Code, I Have Saved It, Replace
      Authenticator App, Switch Off Authenticator App, Get a New Recovery Code, Request a Reset, Authenticator App
      Reset, Reset Authenticator, Sign-In Security, Always On, Not Available.
    - **Readers' words:** people read "authenticator app" and "code", never "TOTP", "2FA" or "MFA". The frontend
      wording test gains a `\bTOTP\b|\b2FA\b|\bMFA\b` deny rule over user-visible strings.
    - **Backend guard:** it adds `services/second_factor.py`, `services/totp.py` and `services/authenticators.py` to
      its modules (rules unchanged).
20. **Rollout.** Nothing changes for anyone at deployment: every login keeps the e-mailed code until it switches the
    app on. `aslms users authenticator-status` gives counts per user type of logins using the app, and one login's
    state with `--email`. It never shows a secret.
21. **Passkeys and security keys: not now (owner).** The method layer would take a `webauthn` method later, as its own
    row and design.

## Data
Migration **0036_authenticator** (new; it revises the head at build time). **0035 is reserved by row 207
`close-case`**. If 0035 has not merged when this is built, take the next free number after the head then. Applied
migrations are never edited. `schema.md` takes the paragraphs below (Groups 0 and 1) **before** the migration is
written.

**`ref_second_factor`** (reference; Group 0):
> code (PK, varchar 40), label varchar(120) NOT NULL, description text NULL, sort_order int NOT NULL default 0,
> is_active bool NOT NULL default true, created_at, updated_at. Seeded from `SecondFactor`: `email` ("E-mail Code",
> "A 6-digit code e-mailed to the login's address", 10) and `totp` ("Authenticator App", "A 6-digit code from an
> authenticator app on the person's phone", 20). Inserted by migration 0036 (`ON CONFLICT (code) DO NOTHING`) and the
> seed (labels on insert only). `otp_codes.method` → RESTRICT. A later SMS row adds `sms` (design
> `totp-authenticator`, decision 3).

**`ref_ticket_kind`** (Group 0): + `authenticator_reset` ("Authenticator App Reset", "Reset a login's authenticator
app after a lost phone; decided by the Super Administrator", sort 20), by migration 0036 and the seed.

**`ref_permission`** (Group 0, seed only): + `admin.sign_in_security` ("Sign-In Security", "Choose which sign-in
methods people may switch on (reserved to the Super Administrator).", module `admin`). It is reserved like
`admin.tickets` (`RESERVED_FUNCTIONS`): enabled for no type, never overridden. It sits in the Administration group of
`PERMISSION_GROUPS`. That makes one row and one active function more than at build time (row 207 also adds one).

**`auth_settings`** (master, versioned; Group 1):
> id (uuid v7 PK), version integer NOT NULL UNIQUE, methods_enabled varchar(40)[] NOT NULL default '{}' (codes of
> optional methods in `ref_second_factor`; `email` is the base method, never listed), reason text NOT NULL (3–500),
> is_current boolean NOT NULL default false, valid_from timestamptz NOT NULL default now(), valid_to timestamptz NULL,
> created_at, updated_at, created_by, updated_by (→ users SET NULL).
> - CHECKs: `ck_auth_settings_current` (is_current = (valid_to IS NULL)); `ck_auth_settings_no_email` (NOT ('email' =
>   ANY(methods_enabled))).
> - Index: partial unique `ix_auth_settings_current` (is_current) WHERE is_current.
> - Versioning: a save inserts a new version and closes the previous one. Values are never updated in place and rows
>   never deleted (as `scoring_settings`).
> - Validation: arrays cannot carry foreign keys, so the service validates each code against `ref_second_factor` and
>   the registry's available optional methods.
> - Defaults: an empty table means `{totp}`. Version 1 (`{totp}`, "Owner's decision of 30 Oct 2026") is inserted by
>   `aslms seed`.
> - Writer: only `services/second_factor.py` (design `totp-authenticator`, decision 4).
> - Meaning: switching a method off stops new set-ups only.

**`user_authenticators`** (master; Group 1):
> id (uuid v7 PK), user_id (→ users RESTRICT; logins are never deleted), state (`authenticator_state` enum: `pending`
> / `active` / `ended`) NOT NULL, secret_ciphertext bytea NULL, secret_nonce bytea NULL (12 bytes), key_fingerprint
> char(8) NULL, algorithm varchar(10) NOT NULL default 'SHA1', digits smallint NOT NULL default 6, period_seconds
> smallint NOT NULL default 30, setup_expires_at timestamptz NULL, setup_attempts smallint NOT NULL default 0,
> confirmed_at timestamptz NULL, last_used_step bigint NULL, last_used_at timestamptz NULL, ended_at timestamptz NULL,
> end_reason (`authenticator_end_reason` enum: `abandoned` / `replaced` / `removed` / `reset_by_ticket` /
> `reset_by_cli`) NULL, ticket_id (→ admin_tickets RESTRICT) NULL, created_at, updated_at, created_by, updated_by
> (→ users SET NULL).
> - CHECKs:
>   - `ck_user_authenticators_secret`: (state = 'ended') equals each of secret_ciphertext IS NULL, secret_nonce IS
>     NULL and key_fingerprint IS NULL.
>   - `ck_user_authenticators_ended`: (state = 'ended') = (ended_at IS NOT NULL) AND (ended_at IS NULL) =
>     (end_reason IS NULL).
>   - `ck_user_authenticators_active`: state <> 'active' OR confirmed_at IS NOT NULL.
>   - `ck_user_authenticators_pending`: state <> 'pending' OR setup_expires_at IS NOT NULL.
>   - `ck_user_authenticators_ticket`: end_reason IS DISTINCT FROM 'reset_by_ticket' OR ticket_id IS NOT NULL.
>   - `ck_user_authenticators_params`: algorithm = 'SHA1' AND digits = 6 AND period_seconds = 30.
> - Indexes: partial uniques `ix_user_authenticators_one_active` (user_id) WHERE state = 'active' and
>   `ix_user_authenticators_one_pending` (user_id) WHERE state = 'pending'; plain `ix_user_authenticators_user_id`.
> - A login with an `active` row signs in with the app only.
> - Secret: AES-256-GCM under `ASLMS_TOTP_KEY`, with associated data `aslms-totp:<id>`. It is wiped (NULL) when the
>   row ends.
> - Abandoned set-ups: a pending row past `setup_expires_at` is ended `abandoned` by the next setup and by the 5-minute
>   session sweep.
> - Never deleted (`aslms_app` SELECT / INSERT / UPDATE). `updated_at` trigger (`MUTABLE_TABLES`).
> - Writer: only `services/authenticators.py` (design `totp-authenticator`).

**`user_recovery_codes`** (derived; Group 1):
> id (uuid v7 PK), user_id (→ users RESTRICT), authenticator_id (→ user_authenticators RESTRICT), code_hash text NOT
> NULL (argon2id of the normalised 20-character code), created_at, ended_at timestamptz NULL, end_reason
> (`recovery_code_end_reason` enum: `used` / `replaced` / `authenticator_ended`) NULL, updated_at.
> - CHECK `ck_user_recovery_codes_ended`: (ended_at IS NULL) = (end_reason IS NULL).
> - Indexes: partial unique `ix_user_recovery_codes_live` (user_id) WHERE ended_at IS NULL;
>   `ix_user_recovery_codes_authenticator_id`.
> - Never deleted (`aslms_app` SELECT / INSERT / UPDATE). `updated_at` trigger.
> - The code itself is never stored, logged or audited (decision 11).

**`otp_codes`** (derived) — one column, one change, one CHECK:
> - `method` varchar(40) NOT NULL default 'email' (→ `ref_second_factor` RESTRICT).
> - `code_hash` becomes NULL-able.
> - CHECK `ck_otp_codes_code_hash`: (method = 'totp') = (code_hash IS NULL).
> - A `totp` row is a sign-in or reset challenge with no sent code. The `id` is still the challenge id; `attempts`,
>   `expires_at` and `consumed_at` keep their meaning.
> - The resend wait and the hourly cap count only rows with `method <> 'totp'`.
> - The CASCADE to `users` is unchanged.

**`user_sessions`** (derived) — one column:
> `signed_in_with` (`sign_in_proof` enum: `email_code` / `authenticator_code` / `recovery_code`) NULL (NULL for
> sessions opened before 0036). A session opened by a recovery code may replace the app without a current code
> (decision 12). `started_at` now reads "the code step (any method)".

**`admin_tickets`** (transaction) — one CHECK and one index:
> - CHECK `ck_admin_tickets_authenticator_reset`: kind <> 'authenticator_reset' OR target_user_id IS NOT NULL.
> - Partial unique `ix_admin_tickets_one_open_authenticator_reset` (target_user_id) WHERE kind =
>   'authenticator_reset' AND status = 'open'.
> - Payload of the kind: `{user_id, reason}`. Result: `{authenticator_id, sessions_ended}`.

**Enums, grants and downgrade:**
- New native enums: `authenticator_state`, `authenticator_end_reason`, `recovery_code_end_reason`, `sign_in_proof`.
- `aslms_app` gets SELECT / INSERT / UPDATE on `auth_settings`, `user_authenticators` and `user_recovery_codes`. Every
  new FK is RESTRICT, so the cascade list is unchanged.
- Downgrade refuses (raises) if any `user_authenticators` row, any `otp_codes` row with `method = 'totp'` or any
  `authenticator_reset` ticket exists. Otherwise it drops what 0036 added and restores `code_hash NOT NULL`.

## Services
- **`services/totp.py` (new; pure, no database):**
  - `new_secret() -> bytes` (20 bytes) and `b32(secret)`;
  - `uri(secret, account, issuer)`;
  - `code_at(secret, step)`, RFC 4226 dynamic truncation;
  - `match(secret, code, now, last_step) -> int | None`: the accepted step among t−1, t, t+1 that is above
    `last_step`, compared in constant time;
  - `qr_svg_data_uri(uri)` with segno;
  - `Secret`, a bytes wrapper with a masked `repr`;
  - `encrypt(secret, row_id, settings) -> (ciphertext, nonce, fingerprint)`;
  - `decrypt(row, settings)`: the current key, then `ASLMS_TOTP_KEY_PREVIOUS`; `AuthenticatorUnavailable` (503) when
    neither fits or the key is missing.
- **`services/second_factor.py` (new):**
  - `SecondFactor`, `METHODS` and `PLANNED`;
  - `EmailMethod` and `TotpMethod`;
  - `method_for(session, user)`: `totp` with an active authenticator, otherwise `email`;
  - `current_settings(session)`: the default on an empty table;
  - `can_set_up(session, method)`;
  - `save_settings(session, actor, user, methods, reason)`: decisions 3 and 4, a new version, audit
    `auth.settings_changed`;
  - `catalogue(session)`: each method with `available`, `enabled`, `always_on`, `needs` and `logins_using`.
- **`services/authenticators.py` (new):**
  - `state(session, user)`;
  - `start_setup(session, actor, user, *, current_code=None, session_row)` (decisions 6 and 12);
  - `confirm_setup(session, actor, user, setup_id, code) -> recovery code`;
  - `check_code(session, user, code, *, purpose) -> int`: under `otp.lock_user`, then the authenticator row lock;
    updates `last_used_step` and `last_used_at`;
  - `new_recovery_code(session, actor, user, code)`;
  - `use_recovery_code(session, user, raw) -> new code | None`;
  - `remove(session, actor, user, code)` (decision 13);
  - `reset(session, actor, user, *, by, reason, ticket=None)` (decisions 14 and 15);
  - `end_abandoned(session, now)`;
  - the notice mails.
  Nothing here logs or audits a secret or a code.
- **`services/auth.py`:**
  - `start_login` opens the challenge through `method_for` (decision 5);
  - `complete_login` dispatches on `row.method` and sets `signed_in_with`;
  - new `complete_with_recovery(session, challenge_id, raw, client, mailer, settings) -> Signed` (+ `recovery_code`);
  - `resend` refuses `totp` challenges (409 `nothing_to_resend`);
  - `confirm_reset` takes `authenticator_code` (decision 16);
  - `LoginStep` gains `method` and `recovery_allowed`; `Signed` gains `recovery_code`.
  The raise-after-flush pattern is kept, so attempts, spent challenges and audit rows commit. `next_step` is
  unchanged.
- **`services/otp.py`:**
  - `issue` and `verify` take `method`;
  - `seconds_until_resend` and `seconds_until_hourly_slot` count only code-sending rows;
  - new `issue_challenge(session, user, purpose, method)`, which writes a `totp` row with no hash.
- **`services/sessions.py`:** `open_session(..., proof)` sets `signed_in_with`; `sweep` also calls
  `authenticators.end_abandoned`.
- **`services/tickets.py`:**
  - a handler `AuthenticatorReset` (`validate`, `check`, `apply`, `describe`, `doc_types = frozenset()`,
    `remark_required = True`);
  - `request_authenticator_reset(session, actor, user, payload)` with the three raisers of decision 14;
  - `approve` asks the handler for its re-check, so the requester-ended check stays `head_change`'s, and for
    `remark_required`;
  - `visible_condition` adds `AdminTicket.requested_by_user_id == user.id`;
  - `ticket_item` reads its target through `describe`;
  - the opening notice to the target;
  - `_insert` maps the new partial unique index to 409 `ticket_open`.
- **Access, seed and settings modules:**
  - `services/access.py`: `RESERVED_FUNCTIONS` adds `admin.sign_in_security`.
  - `services/access_seed.py`: the label and the group.
  - `services/seed.py`: `ref_second_factor`, the ticket kind and `auth_settings` version 1.
- **`services/preflight.py`:**
  - `ASLMS_TOTP_KEY` missing, not 32 bytes of URL-safe base64, or equal to `ASLMS_JWT_SECRET`: an error in prod, a
    warning otherwise;
  - `ASLMS_TOTP_KEY_PREVIOUS` equal to the current key: a warning;
  - findings name the variable, never the value.
- **`core/config.py` and `.env.example`:**
  - `ASLMS_TOTP_KEY` and `ASLMS_TOTP_KEY_PREVIOUS` (`SecretStr`);
  - `AUTH_TOTP_ISSUER=ASLMS`, `AUTH_TOTP_SETUP_MINUTES=15` (5–60), `AUTH_TOTP_SETUP_ATTEMPTS=5`,
    `AUTH_TOTP_SETUPS_PER_HOUR=5`;
  - the `.env.example` comment tells how to generate the key and to keep a sealed offline copy.
- **CLI:**
  - `aslms users reset-authenticator --email --reason` (decision 15);
  - `aslms users authenticator-status [--email]`;
  - `aslms ops totp-rekey [--apply]` (decision 10; audited `auth.totp_rekeyed` `{rows}`).
- **Dependency:** `segno>=1.6,<2` in `backend/pyproject.toml`.
- **Docs in the build commit:**
  - `docs/operations.md`:
    - a new "Server clock" section: chrony or systemd-timesyncd on the host against the State Data Centre's NTP
      server or the national time service; `timedatectl` shows "System clock synchronized: yes"; containers use the
      host clock; a daily look in section 14;
    - section 5: `ASLMS_TOTP_KEY` rotation and its sealed offline copy;
    - section 15: "a person's authenticator codes are always refused", which points to the clock or the key.
  - The decisions log records the change to `otp-and-profile` decision 1.

**Audit actions.** No row carries a secret, a key, a code, a recovery code or a password.

| Action | `after` holds |
|---|---|
| `auth.settings_changed` | before and after `{version, methods_enabled, reason}` |
| `auth.otp_failed` | as today + `method`; `purpose` may be `login`, `password_reset`, `replace` or `remove` |
| `auth.login` | as today + `method`, `drift` |
| `auth.authenticator_setup_started` | `{authenticator_id, replacing}` |
| `auth.authenticator_setup_failed` | `{authenticator_id, attempts}` |
| `auth.authenticator_enrolled` | `{authenticator_id, replaced, signed_in_with}` |
| `auth.authenticator_removed` | `{authenticator_id}` |
| `auth.authenticator_reset` | `{authenticator_id, by, ticket_ref, reason, sessions_ended}` |
| `auth.recovery_code_issued` | `{authenticator_id, reason: enrolment / used / requested}` |
| `auth.recovery_code_used` | `{authenticator_id}` |
| `auth.totp_rekeyed` | `{rows}` |
| `ticket.opened`, `ticket.approved`, `ticket.rejected`, `ticket.withdrawn` | as today, with kind `authenticator_reset` |

`FAILURE_ACTIONS` is unchanged.

## API
All errors carry `{code, message}`; 429 adds `retry_after`. "Public" means no token. "Signed in" means any valid token
and acts on the caller's own login. Nothing here reads cases, so the case visibility rule does not apply. Answers that
carry a secret or a recovery code send `Cache-Control: no-store`. No new endpoint joins the first-sign-in exempt
list: a login sets the app up only after its first sign-in steps.

| Method and path | Function | Request | Response | Notes |
|---|---|---|---|---|
| `POST /auth/login` | public | as built | `{step: "otp", challenge_id, method, recovery_allowed, sent_to (masked or null), expires_in, resend_after}` | `method` is `totp` for a login with the app, else `email`. Errors as built. |
| `POST /auth/otp/verify` | public | as built | as built | Checked by the challenge's method. 401 `otp_invalid` (a replayed code too) with `attempts_left`; 503 `authenticator_unavailable` (key missing). |
| `POST /auth/otp/resend` | public | as built | as built | On a `totp` challenge: 409 `nothing_to_resend`. |
| `POST /auth/recovery/verify` | public | `{challenge_id, recovery_code, device_token?, device_label?}` | `TokenOut` + `recovery_code` (new, once) | 401 `otp_invalid` with `attempts_left`; 409 `no_recovery_code` (also for an e-mail challenge); 429 `locked`. |
| `POST /auth/password-reset/confirm` | public | as built + `authenticator_code?` | 204 | 409 `authenticator_code_required` (logins with the app, after a correct e-mailed code); 401 `otp_invalid` as built. |
| `GET /me` | signed in (exempt, as built) | — | as built; `user` + `authenticator_enabled` | |
| `GET /me/authenticator` | signed in | — | `{available: bool, state: none / pending / active, confirmed_at, last_used_at, has_recovery_code, can_replace_without_code}` | Never the secret. |
| `POST /me/authenticator/setup` | signed in | `{current_code?}` | `{setup_id, otpauth_uri, key_text, qr_data_uri, issuer, account, expires_in, attempts}` | 409 `method_disabled`, `already_enrolled`; 401 `otp_invalid` (a wrong `current_code`, counted); 429 setups an hour; 503 `authenticator_unavailable`. |
| `POST /me/authenticator/confirm` | signed in | `{setup_id, code}` | `{recovery_code, authenticator: state}` | 401 `otp_invalid` with `attempts_left` (not counted); 410 `setup_expired` (also after 5 tries). |
| `POST /me/authenticator/recovery-code` | signed in | `{code}` | `{recovery_code}` | 401 `otp_invalid` (counted); 409 `not_enrolled`. |
| `POST /me/authenticator/remove` | signed in | `{code}` | 204 | 401 `otp_invalid` (counted); 409 `not_enrolled`. Any login, the Super Administrator included. |
| `POST /me/authenticator/reset-request` | signed in | `{reason}` | 202 `TicketDetailOut` | Opens an `authenticator_reset` ticket for the caller. 409 `ticket_open`, `not_enrolled`; 403 `super_admin_cli_only`. |
| `GET /admin/sign-in-security` | `admin.sign_in_security` | — | `{current: {version, methods_enabled, reason, changed_by, valid_from}, methods: [{code, label, available, enabled, always_on, needs?, logins_using}], history: [...]}` | |
| `PUT /admin/sign-in-security` | `admin.sign_in_security` | `{methods_enabled, reason}` | as GET | 422 `method_not_available` (`sms`), `bad_field` (`email` or an unknown code; reason length). |
| `POST /admin/tickets/authenticator-reset` | `users.reset_password` or `admin.tickets` | `{user_id, reason}` | 202 (open) or 201 (the Super Administrator's, applied) `TicketDetailOut` | Non-super-admins are scoped by `login_scope_member(…, "reset_password")`: 404 outside scope, as `/admin/users`. 403 `super_admin_cli_only`; 409 `ticket_open`, `not_enrolled`. |
| `POST /admin/tickets/{ref}/approve` | `admin.tickets` (as built) | as built | as built | For this kind `remark` is required (422 `bad_field`); 409 `ticket_stale` when the app is no longer active. |
| `GET /admin/tickets`, `/{ref}`, `/reject`, `/withdraw` | as built | | | Kind `authenticator_reset` is listed; the requester sees their own. |
| `GET /admin/users/{id}` | `users.view` (as built) | | + `authenticator: {enabled, confirmed_at, last_used_at, open_reset_ticket}` | Under the existing login visibility; lets an administrator see who uses the app before raising a reset. |

## Jobs
No new job. The existing 5-minute session sweep (`aslms sessions sweep`) also ends pending set-ups past
`setup_expires_at` (`abandoned`, secret wiped), in the same transaction and with no audit row; the setup row is its own
record.

## Tests
**Unit:**
- `tests/unit/test_totp.py`:
  - the RFC 6238 SHA-1 vectors;
  - the window accepts t−1, t and t+1 and refuses t±2;
  - replay: a step not above `last_step` is refused;
  - the comparison is constant-time;
  - URI shape and parameters; base32 grouping;
  - the QR data URI is SVG;
  - encrypt / decrypt round trip; a wrong row id (associated data) fails; the previous key decrypts; the fingerprint;
  - `repr(Secret)` is masked.
- `tests/unit/test_recovery_code.py`: format, randomness source, normalisation (case, dashes, I / L / O), argon2 verify.
- `tests/unit/test_second_factor.py`:
  - `method_for` with and without an active authenticator, and with `totp` switched off for new set-ups;
  - `sms` is planned and unavailable;
  - `email` cannot be listed;
  - the catalogue shapes.
- `tests/unit/test_preflight.py`: key missing, short, malformed, equal to the JWT secret, or the previous key equal to
  the current (an error in prod, a warning in dev; no value printed).
- **Wording:** the backend guard's new modules; the frontend deny rule for TOTP, 2FA and MFA.

**Database.** The files are `tests/db/test_authenticator.py`, `test_auth_methods.py`,
`test_authenticator_reset_tickets.py`, `test_sign_in_security.py` and `test_migration_0036.py`, run with a
`RecordingMailer`. The helper `auth_support.sign_in_with_app(api, email, password, secret)` computes the code and moves
`last_used_step` back when a test signs the same login in twice within one step (the clock, not the rule). The existing
`sign_in` helper is unchanged, because no login has the app unless a test sets it up.
- **Enrolment:**
  - setup returns the secret once and `GET` never does;
  - a right first code activates the app and returns a recovery code;
  - 5 wrong codes expire the setup and do not count toward the lock (11 wrong setup codes leave sign-in open);
  - an expired setup answers 410;
  - a second setup abandons the first and wipes its secret;
  - more than 5 set-ups an hour answers 429;
  - with `totp` switched off for new set-ups, setup answers 409 `method_disabled`.
- **Always the app once switched on:**
  - after confirmation the next `POST /auth/login` answers `method: "totp"` and sends no mail;
  - an e-mailed code is never issued for that login: resend answers 409, and no route turns the challenge into e-mail;
  - an e-mailed code from before enrolment, or a guessed `otp_codes` id of method `email`, cannot complete its sign-in
    (enrolment spends the login's live sign-in codes);
  - `auth.login` records `method: totp`;
  - a login without the app is unchanged (e-mailed code, as today).
- **Switched off for new set-ups:** existing app logins still sign in with the app.
- **Window and replay:**
  - codes at t−1 and t+1 are accepted and t+2 refused;
  - the same code twice answers `otp_invalid` the second time, also across two challenges;
  - the confirmation code cannot be reused to sign in.
- **Lock counting:**
  - 10 failures mixing wrong app codes, wrong recovery codes and a wrong `current_code` / remove code give 429
    `locked`;
  - each writes `auth.otp_failed` with the method;
  - no mail is sent after wrong codes;
  - the attempt counter and the audit row of a wrong app code survive the 401 (read back in a new session).
- **Recovery:**
  - a recovery code signs in once, returns a new code and sets `signed_in_with = recovery_code`;
  - the old code is refused afterwards;
  - in that session, setup without `current_code` replaces the app (the old one ends `replaced`); in a session opened
    with the app code, the same call answers 409 `already_enrolled`;
  - `POST /me/authenticator/recovery-code` rotates;
  - no recovery code appears in a mail, a log or an audit row.
- **Switching off:**
  - any login, the Super Administrator included, switches off with a current code;
  - the next sign-in uses the e-mailed code;
  - a wrong code is counted;
  - no password or recovery code is accepted in its place;
  - the notice is mailed; the session is kept.
- **Password reset:**
  - a login without the app resets with the e-mailed code alone;
  - a login with the app gets 409 `authenticator_code_required` after a correct e-mailed code (no failure counted, the
    code still usable), then succeeds with an app code;
  - a wrong app code is counted;
  - an app code without the e-mailed code is never accepted; a recovery code is refused.
- **Tickets:**
  - a department admin raises for an officer in scope: the opened alert reaches the Super Administrator and the notice
    reaches the officer;
  - out of scope answers 404; for a head or a Department Administrator, 403;
  - naming the Super Administrator answers 403 `super_admin_cli_only`;
  - a second open ticket answers 409;
  - approval without a remark answers 422;
  - approval ends the app, the recovery code and every session (the old access token gets 401) and mails the notice;
    the person then signs in by e-mail;
  - approval after the person switched the app off answers `ticket_stale`;
  - the Super Administrator's direct reset of a Department Administrator is recorded as approved;
  - self-raise from a session works;
  - the requester sees the ticket;
  - **only the ticket or the CLI resets another login's app:** a scan of the API routes plus direct calls show no
    other path that ends another login's authenticator.
- **CLI:**
  - `reset-authenticator` resets the Super Administrator's own app (audited `by: cli`) and refuses every other login;
  - `authenticator-status` prints counts and no secret;
  - `totp-rekey` dry run changes nothing; `--apply` re-encrypts, and old-key rows still verify afterwards.
- **Method setting:**
  - only the Super Administrator: `admin.sign_in_security` is reserved, so a matrix change or a grant of it is refused;
  - `sms` answers 422, and `email` 422;
  - an audited version is written; an empty table means `{totp}`.
- **No secret anywhere:** after enrolment, sign-in, recovery, replacement, switching off and reset:
  - a scan of every `audit_log` row, every `caplog` record and every recorded mail finds neither the base32 secret,
    nor a code just used, nor a recovery code;
  - the stored ciphertext does not contain the secret;
  - an ended row has NULL ciphertext.
- **Migration:**
  - 0036 up, down (empty tables), up;
  - down refuses with an authenticator row;
  - `ref_second_factor` and the ticket kind exist after up;
  - existing `otp_codes` rows read as `email`.

**Existing tests:** `test_access_seed` counts one more reserved function. The head-change ticket tests gain only the
"requester sees their own" clause.

**Portal (row 210), Vitest:**
- the code page: the e-mail variant as today; the app variant (no resend, no e-mail link, Use a Recovery Code);
- the recovery entry, and the new recovery code shown with I Have Saved It before continuing;
- the My Profile section: off, setup steps with the advice text, on, replace, new recovery code, switch off, lost
  phone, Request a Reset;
- the forgotten-password page asks for the app code on 409;
- Sign-In Security: E-mail Code Always On, SMS greyed with no switch;
- the ticket kind in the list and detail, with the remark required on approve;
- the Reset Authenticator action in User Details;
- the BFF handlers send `Cache-Control: no-store` and never put the secret or a recovery code in a cookie or a log;
- the Title Case and wording guards.

The new screens join the `uicheck` route list.

## Verification
**Row 209 (backend), by the integrator:**
1. `ruff check` is clean; `pytest -q` is green.
2. `schema.md` holds the paragraphs above. `aslms ops migrate` reaches 0036 (or the build's number), and
   `alembic heads` shows one head.
3. The owner adds `ASLMS_TOTP_KEY` to `.env` and keeps a sealed offline copy. It is generated with
   `python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`. The
   integrator never reads `.env`. Then `docker compose build`, `init` (the seed; preflight shows no `ASLMS_TOTP_KEY`
   finding) and `up` with the court-data switch as usual.
4. `aslms users authenticator-status` shows 0 logins with the app. Every sign-in still uses the e-mailed code.
5. After the owner's check below, `docker compose logs api worker` contains no base32 secret, no code just used and no
   recovery code (grep for the values used).
6. This query shows the rows of the owner's check:
   `SELECT action, count(*) FROM audit_log WHERE action LIKE 'auth.authenticator%' OR action LIKE 'auth.recovery%' OR action = 'auth.settings_changed' GROUP BY 1`.
7. The runbook's "Server clock" section is followed on the host, and `timedatectl` shows the clock synchronised.

**Row 210 (portal), by the integrator:** the portal checks (lint, type check, Vitest) are green, and `uicheck` passes
at 375, 768 and 1280 px on the private network (runbook section 16). The run covers the code page variants, the My
Profile section, Sign-In Security and the ticket screens.

**The owner's live check with a real phone** (http://localhost:3000; any authenticator app):
1. **Switch on:** as an officer, open My Profile → Authenticator App → Set Up. Scan the QR code; on a second app, type
   the key to check that the text works too. Enter the code. A recovery code is shown once: write it down and press
   I Have Saved It. A notice e-mail arrives.
2. **Always the app:** sign out and sign in. After the password, the page asks only for the app's code: no e-mail
   arrives and there is no e-mail link. The code signs in. Entering the same code again at once is refused.
3. **Recovery code:** use it once (Use a Recovery Code). It signs in and a new code is shown; the old one is refused
   afterwards. In that session, Replace Authenticator App sets up the app again without the old code.
4. **Switch off:** Switch Off Authenticator App asks for a current code. Afterwards the next sign-in e-mails a code
   again, and a notice arrives.
5. **The Super Administrator:** switch the app on, then reset it from the server with
   `aslms users reset-authenticator --email … --reason …`. The Super Administrator's session ends, a notice arrives,
   and the next sign-in uses the e-mailed code.
6. **Ticket reset:** a Department Administrator switches the app on. As the Super Administrator, Reset Authenticator on
   that login with a reason (a direct ticket). The Department Administrator's open session ends, a notice arrives,
   and the next sign-in uses the e-mailed code. Repeat for an officer through the department administrator's Request
   a Reset and the Super Administrator's approval.
7. **Sign-In Security:** E-mail Code is Always On, and Text Message (SMS) shows Not Available with its explanation and
   no switch. Switching the authenticator app off for new set-ups hides Set Up for officers without the app, while
   step 1's officer still signs in with the app. The change appears in the history and the audit log.
8. **Clock:** set the phone's clock 2 minutes wrong and codes are refused; correct it and they are accepted.

## Open questions
None. The owner decided every point on 30 Oct 2026: the app is optional for every login, with no required type and no
gate; once switched on it is always the app; anyone may switch it off with a current code; one on-screen rotating
recovery code; ticket-only reset by the Super Administrator, and the command line for the Super Administrator's own;
SMS as a provision only.

Two design choices go to the owner for approval with the note, though they are not open questions:
- **Replacing the app with the recovery code (decision 12).** A session opened with the recovery code may replace the
  app without the old phone. This is the self-service purpose of the recovery code.
- **Who raises a reset ticket (decision 14).** The department administrator in scope, the person from an open session,
  or the Super Administrator directly. This follows the existing head-change pattern.

**Proposed backlog split:**
- **Row 209 `totp-authenticator` (backend):** migration 0036, services, API, CLI, preflight, runbook, `schema.md`,
  tests.
- **Row 210 `totp-authenticator-portal` (portal):** the code page app variant, the recovery entry and the new-code
  step, the My Profile → Authenticator App section, Sign-In Security under Administration, the ticket kind, the Reset
  Authenticator and Request a Reset actions, the BFF handlers, the Vitest and uicheck additions, and the owner's live
  check above. It depends on row 209.
