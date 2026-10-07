# otp-and-profile (backlog row 7) - report of 2026-10-08

Merge commit on main: 087ae0b (squash of feature/otp-and-profile, 10 commits); tag `feature/otp-and-profile-done`.
Design: [docs/design/otp-and-profile.md](../design/otp-and-profile.md), approved 7 Oct 2026 with the owner's two
answers (a code at every sign-in; mobile number mandatory).

## What changed
- 54 files, +4549 / -188. Migration 0010 (`0010_otp_profile.py`): `users` gains `password_changed_at`,
  `must_change_password` (back-filled from `must_confirm_profile`) and `profile_confirmed_at`; new table
  `user_devices` (never deleted); `refresh_tokens.device_id`; index `ix_otp_codes_user_purpose_created`. The downgrade
  refuses while a `user_devices` row exists. `schema.md` was updated before the migration. Uses the existing
  `otp_codes` table of 0001.
- Services: `otp.py` (issue, verify, resend wait, masking, lock), `auth.py` (two-step sign-in, resend, password reset
  request and confirm, own password change, refresh with reuse detection, devices, lock check, sign-out everywhere),
  `passwords.py` (policy, hashing), `profile.py` (get, confirm, update); changes to `users.py` (e-mail change,
  `set_password`, `end_sessions`, `end_codes`), `notifications.py`, `mailer.py`, `api/deps.py` (token-age check,
  first-sign-in gate), `api/security.py`.
- Endpoints: `POST /auth/login` (now step one, answers `step: "otp"`), `/auth/otp/verify`, `/auth/otp/resend`,
  `/auth/password-reset/request` and `/confirm`, `/auth/refresh`, `/auth/logout`; `POST /me/password`, `GET` and
  `PATCH /me/profile`, `POST /me/profile/confirm`, `GET /me/devices`, `POST /me/devices/{id}/revoke`; `PATCH
  /admin/users/{id}` accepts `email`; `POST /admin/users/{id}/password` forces a change.
- CLI: `aslms users set-password` forces a change and applies the policy; new `aslms users sign-out --email`.
- Settings (`.env.example`): `OTP_TTL_MINUTES`, `OTP_MAX_ATTEMPTS`, `OTP_RESEND_SECONDS`, `OTP_MAX_PER_HOUR`,
  `LOGIN_MAX_FAILURES`, `LOGIN_LOCK_MINUTES`.
- Tests: `tests/unit/test_auth_rules.py`; `tests/db/` `test_auth_otp.py`, `test_auth_resend_and_races.py`,
  `test_profile.py`, `test_api_auth.py`, `test_api_auth_gaps.py`, `test_api_auth_negative.py`,
  `test_migration_0010.py`; `tests/db/auth_support.py::sign_in` replaces the direct logins of the existing API tests.

## Gates
- `ruff check .` (backend): All checks passed.
- `pytest -q` (backend): 653 passed, 51 warnings in 501 s (database tests against the Compose `postgres`).
- `docker compose build` (root): succeeded (init, api, worker, scheduler images built).
- `git status`: clean on the branch; design status `approved`; decisions-log entry and backlog row present.

## Review findings and how each was closed
Blocking (both closed in commit 0c3236e, recorded as deviations 17 and 18 of the design note):
1. Resend of a sign-in challenge spent by wrong codes survived a credential change. Closed: resend accepts only the
   newest, unexpired challenge, live or spent by wrong codes, created after the login's `password_changed_at`
   (deviation 17); tests in `test_auth_resend_and_races.py`.
2. No row locks on `otp_codes` and the lock counter, so parallel guesses beat the 5-try limit and the lock. Closed:
   sign-in steps of one login are serialised by `SELECT ... FOR UPDATE` on the `users` row, then the `otp_codes` row
   (deviation 18; `otp.py` `_lock_user`, `_lock_code`); race tests added.

Advisory (not fixed in this cycle; carried to backlog row 35 `auth-hardening` unless noted):
- Reset requests and failed reset codes count toward the shared hourly cap and the sign-in lock, so an
  unauthenticated caller who knows an e-mail can keep an officer locked out; a `locked` 429 reveals that the account
  exists. Owner decision needed (separate cap for reset codes, or not counting reset failures toward the sign-in lock).
  Per-IP throttling goes with row 16 (deployment checklist) and row 33.
- Password-reset and code mails are sent synchronously: response time reveals whether an account exists, and the code
  mail is sent while the `users` row lock is held (a slow mailer holds up other steps of that login for up to 20 s).
- `refresh()` reads the token without a row lock (two parallel refreshes both rotate it, reuse detection is bypassed
  by timing); tokens revoked by disable or an earlier reuse event count as rotated (false `auth.refresh_reused`,
  new sessions ended by a stale tab).
- `POST /me/password` without a device token issues a refresh token with no device, so `/me/devices` cannot end it.
- `PATCH /admin/users/{id}` stores `mobile` without `profile.normalise_mobile` (mandatory 10-digit rule only on the
  self-service paths).
- The API refuses an e-mail change on the super admin's login as "CLI only", but no CLI command changes an e-mail.

## Deviations
Eighteen items in the design note's Deviations section; none changes a business rule. Main ones: no device trust (owner
review); `new_device` stays in the enum but nothing issues it; reset confirm answers every failed code alike; a failed
send leaves no `otp_codes` row; a logged-out refresh token is not reuse; a reset revokes tokens but not devices; an
out-of-scope e-mail change answers 404; a refused profile confirmation never half-applies.

## Follow-up rows added to the backlog
- 33 `auth-retention` (pruning of old `otp_codes` and `refresh_tokens`; per-IP throttling with row 16).
- 34 `mobile-verification` (SMS verification once a gateway exists; shares the gateway with row 27).
- 35 `auth-hardening` (the advisory findings above).

## Load status (`aslms queue-status`, 8 Oct 2026)
- causelist_day: done 20, pending 604, skipped 18.
- dossier: done 11466, failed 46, pending 288, skipped 18.
- masters: done 1. order_pdf: pending 94036. status_batch: done 22, skipped 1.

## After the merge
- The dev database is still at the previous revision; upgrade to 0010 when the merged images are rebuilt
  (`docker compose up -d --build`, the `init` service runs the migration). Live check (design Verification steps 2 to 7)
  needs the Mailtrap sandbox URL in `.env`; a working mail service is required to sign in.
