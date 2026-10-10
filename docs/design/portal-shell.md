# Design: Next.js portal: sign-in, shell, dashboard, user and access administration screens, Compose `web` service

```
slug: portal-shell
status: approved
author: architect
date: 2026-10-09
approved_by: owner (nayanlhuzuri) on 2026-10-10
```

## Context
The plan, §2.1 (delivery layer): "Backend API (Python) serving the portal; web portal (Next.js); login, roles and
visibility rules applied to every request". §2.2: web portal Next.js, deployed as Docker containers (Compose).
§5.1 (Dashboard): "The first screen after login, showing each user what needs their attention. Its content
depends on the user's role": State oversight (case counts by department, upcoming hearings across the State,
overdue actions, compliance), Department (new recommendations awaiting review, hearings this week, cases with
pending action, cases in custody of each office), Officer (own cases, own pending actions, own alerts). §5.11
(Administration): departments, directorates and offices; users and roles; notification settings. §8.1: individual
accounts with OTP, role-based permissions and the visibility hierarchy applied to every request, "NAPIX credentials
stored securely and never exposed to the browser". Annexure B, "Department dashboard" and "Department mapping":
the visual direction (dark navy sidebar with the portal name and "Gauhati High Court", the signed-in name,
designation and office at its foot; a header with breadcrumb, case search and the alert bell; serif headings, sans
body, monospace case numbers; tiles, an upcoming-hearings list with "Within 48 h" / "This week" badges, a
"Needs attention" list; administration in tabs).

Backlog row 11: "Next.js portal: sign-in, shell, dashboard, user and access administration screens, Compose `web`
service". Earlier items left their screens here: `offices-admin` ("the portal screens (`portal-shell`)"),
`user-memberships` ("Portal screens for memberships, the ticket panel and the exit dialog (`portal-shell`)"),
`otp-and-profile` ("Portal sign-in screens and httpOnly cookie handling (row 11)"), `reports-dashboards` ("the
dashboard goes into row 11").

In place today (used, not rebuilt): the FastAPI app (`backend/aslms/api/main.py`, no CORS, no path prefix) with
`/auth/login` → `/auth/otp/verify` (tokens, `next_step` `ready|change_password|confirm_profile`, a `device_token`
once per new device), `/auth/otp/resend`, `/auth/password-reset/request|confirm`, `/auth/refresh` (rotating, a
rotated token presented again ends **every** session of the login), `/auth/logout`, `/me`, `/me/password` (returns
a fresh token pair), `/me/profile` (+ `/confirm`), `/me/devices` (+ `X-Device-Token`), `/me/notification-preferences`;
`/dashboard`, `/dashboard/me|department|state`; `/alerts/counts`; `/admin/users` (+ lookup, memberships, exit
preview, end, reactivate, primary, per-membership functions and documents), `/admin/permissions`,
`/admin/access/types`, `/admin/offices` (+ tree, detail, create, edit, deactivate, reactivate, admins, the admin
swap), `/admin/designations`, `/admin/tickets` (head change, approve, reject, withdraw, documents). Errors carry
`detail` as `{code, message, ...}`, as a plain string (the `require` 403s and some 404s) or as FastAPI's 422 list.
The first-sign-in gate is server-side (403 `password_change_required` / `profile_confirmation_required`). Access
tokens live 30 minutes, refresh tokens 14 days. Mail links already point at the portal: `<PORTAL_BASE_URL>/cases/<ref>`
and `<PORTAL_BASE_URL>/admin/tickets/<ref>` (refs with `/` written as `-`; the API resolves that form).

Not covered here: the case inbox, search, case detail, claim / dismiss / transfer and the matching screens
(counsel codes, keywords, patterns, watchlist, scoring settings) — row 12 `portal-cases`; custody, stages, notes,
uploads on cases, alerts list and calendar — row 13 `portal-workflow`; the Case Assistant — row 14; the reports
screen — row 39; the audit search and data-health / NAPIX buttons — row 41; the SourceTrace ingestion screen
(`/admin/sourcetrace/*`) — no row names it yet, the scribe adds it to row 41's scope. A browser end-to-end suite
(Playwright) goes with row 15 `github-and-ci`; the reverse proxy and TLS with rows 16 and 24.

## Decisions
1. **Next.js App Router, TypeScript strict, in `frontend/`.** Next.js 16 (the current stable major; exact version
   pinned in `package-lock.json`), React 19, Node 22 LTS in the image (the local Node 20.18 also satisfies Next 16's
   ≥ 20.9). Alternatives: Pages Router (legacy API), a SPA with Vite (the plan names Next.js). The folder name is the
   one in the decisions log (monorepo `backend/`, `frontend/`). Built new; the v3 portal under `ASLMS-legacy` was
   read for lessons only (it used the same backend-for-frontend idea and had no tests — both lessons kept).
2. **Backend-for-frontend; tokens never reach browser JavaScript.** The browser talks only to the Next.js server.
   Session route handlers (`/api/session/*`) call the API's token endpoints and keep the tokens in httpOnly cookies;
   a relay (`/api/backend/[...path]`) forwards every other call to `API_BASE_URL` with `Authorization: Bearer`.
   Alternatives: tokens in `localStorage` (readable by any injected script), the API setting cookies itself (needs
   CORS or a shared origin and changes every auth endpoint). The API stays unexposed to the browser and unchanged.
3. **Cookies.** `aslms_at` (access token; `Max-Age` = `expires_in` − 30 s), `aslms_rt` (refresh token; 14 days,
   from `ASLMS_REFRESH_TOKEN_DAYS` passed to the web service), `aslms_device` (the device token, 400 days, kept on
   sign-out so the device is known next time), `aslms_challenge` (the sign-in or reset challenge id, 15 minutes,
   path `/api/session`). All `HttpOnly`, `SameSite=Lax`, `Path=/` unless stated, `Secure` unless
   `COOKIE_SECURE=false` (default `true`; browsers accept Secure cookies on `http://localhost`, so the local pilot
   works; `false` only for a closed-network pilot over plain HTTP until row 16 brings TLS). `Lax` rather than
   `Strict` so a link in a notification mail opens signed in; cross-site writes are stopped by decision 5.
4. **Refresh is single-flight in the web server.** Because a rotated refresh token presented twice ends every
   session (otp-and-profile), parallel requests (the dashboard loads its blocks in parallel) must not refresh
   twice. The relay keeps an in-memory map keyed by the SHA-256 of the refresh token: concurrent requests share one
   `/auth/refresh` call, and the new pair is remembered for 30 seconds so a request still carrying the old cookie
   gets the new pair instead of presenting the old token again. The relay refreshes when `aslms_at` is missing and
   `aslms_rt` present, or once after an API 401; if the refresh fails (`refresh_invalid`, `session_ended`) every
   session cookie but the device cookie is cleared and the browser gets 401 `signed_out`. This is correct for one
   `web` process (the Compose pilot); several instances would need sticky sessions or a shared store (noted for
   row 16). Alternative: refresh from the browser (impossible with httpOnly tokens) or a grace window in the API
   (weakens reuse detection).
5. **Cross-site request protection.** The relay and session handlers accept a non-GET request only with the header
   `X-ASLMS-Request: 1` (set by the portal's fetch wrapper; a cross-site form cannot set it and a cross-site script
   triggers a preflight the web server never approves) and, when the browser sends `Origin`, only the origin of
   `PORTAL_BASE_URL`. Otherwise 403 `csrf`. No CORS headers are ever sent.
6. **What the relay forwards.** Request: method, body streamed (multipart uploads included, `duplex: "half"`),
   `Content-Type`, `Accept`, `User-Agent` (audit rows and device labels show the browser), `X-Device-Token` (from
   `aslms_device`, never from the browser), `X-Forwarded-For` (decision 7). Never the browser's cookies or any
   `Authorization` it sends. Response: status, body streamed, and only `Content-Type`, `Content-Length`,
   `Content-Disposition`, `Cache-Control`, `Retry-After`, `X-Total-Count`; never `Set-Cookie`. Every relayed
   response gets `Cache-Control: no-store` unless the API set one. Paths are refused (404) when they contain `..`,
   an encoded slash or backslash, `//`, or match the denylist: `/auth/*`, `/me/password`, `/docs`, `/redoc`,
   `/openapi.json`. The token-returning operations (`/auth/otp/verify`, `/auth/refresh`, `/me/password`) are listed
   in `frontend/src/server/token-routes.json`, which the relay reads and a backend test checks against the
   OpenAPI (Tests), so a future endpoint that returns tokens cannot be relayed by accident. Time limit
   `RELAY_TIMEOUT_SECONDS` (120); an unreachable API answers 502 `api_unavailable`.
7. **Client address in audit rows.** Without forwarding, every portal action would be audited with the web
   container's address. The relay sends `X-Forwarded-For` with the client address the Next.js server reports; the
   API trusts it only from the web container: the Compose project gets a network with a fixed subnet
   (`ASLMS_SUBNET`, default `172.28.0.0/24`), `web` a fixed address (`WEB_IP`, default `172.28.0.10`), and the `api`
   command adds `--proxy-headers --forwarded-allow-ips ${WEB_IP}`. The address published to the host (port 8000,
   used by the CLI and tests) is not trusted. Known limit: until the row-16 reverse proxy overwrites the header, a
   browser could put a false address in its own `X-Forwarded-For`; recorded for row 16.
8. **Sign-in screens follow the API's steps exactly.** `/login` (e-mail, password) → `/login/code` (six digits, the
   masked `sent_to`, a resend button with the server's `resend_after` countdown, `attempts_left` on a wrong code,
   `otp_expired` sends the user back to `/login`) → by `next_step`: `/welcome/password` (current and new password,
   the policy shown: 10+ characters, a letter and a digit) → `/welcome/profile` (name, mandatory Indian 10-digit
   mobile, notification preferences, memberships read-only) → the dashboard. `/forgot` (e-mail; the same neutral
   message whatever the answer) → `/forgot/code` (code, new password twice) → `/login` with "password changed,
   sign in". `locked` / `too_many_codes` show the wait from `retry_after`; `mail_failed` / `mail_not_configured`
   say mail is unavailable and to contact the administrator. No bypass, no "trust this device" box (owner's answer
   in otp-and-profile). A `next` parameter is honoured only as a relative path starting with one `/`.
9. **The first-sign-in gate is the server's.** The fetch wrapper turns 403 `password_change_required` /
   `profile_confirmation_required` from any call into a redirect to the matching welcome page; the portal adds no
   rule of its own.
10. **Page gating is convenience; authority is the API.** The Next.js request interceptor (`proxy.ts`, the Next 16
    name for middleware) sends a page request without `aslms_rt` to `/login?next=…`, and the navigation shows only
    entries whose functions appear in `/me.functions`. Every figure, list and action still comes from the API,
    which enforces functions, scope and visibility; a hidden button that is called anyway gets the API's 403. The web
    server has no database access and holds no data beyond the session cookies.
11. **Data loads in the browser through the relay.** Pages are client components using TanStack Query (cache,
    parallel loading, invalidation after writes; rows 12–13 need the same) over one fetch wrapper; server components
    render only static frames. Alternative: server components reading the API with the cookie (a second auth path
    to test). Lists are not cached across sign-out (the query cache is cleared on sign-out and on `signed_out`).
12. **No acting-membership switch.** The API picks the membership that holds the function for each action
    (user-memberships, audit-screens deviation 2), so the shell only shows context: the sidebar foot names the person,
    the primary membership's designation and office, and opens a list of all memberships. Where the API needs a
    department (`/dashboard/department?department=`), the screen shows a department selector built from
    `/dashboard`.
13. **Shell and navigation.** Sidebar entries are declared once in `src/lib/routes.ts` with their functions and a
    `built` flag. Built here: Dashboard (`/`) and Administration (`/admin/...`, shown with any of `users.view`,
    `offices.manage`, `admin.designations`, `access.manage_types`, `users.propose_head`, `admin.tickets`). Declared
    but hidden until their rows: Case inbox, Search, Alerts & calendar, Reports, Audit log, Data health; the header
    search box appears with row 12, and a case reference renders as plain text (not a dead link) until the case page
    exists. The header shows the unread alert count from `/alerts/counts` (polled every 2 minutes, matching the
    notification job), linking to the dashboard's alert list until row 13 builds `/alerts`. The user menu: My
    profile, Sign out.
14. **Dashboard (`/`).** `GET /dashboard` decides the blocks; each block loads separately (`/dashboard/me`,
    `/dashboard/department?department=CODE`, `/dashboard/state`) and fails alone with a retry. Department block, as
    in Annexure B: tiles (recommendations high + medium awaiting review, hearings in 7 days with the number within
    48 h, pending actions with overdue, cases claimed and active), the upcoming-hearings list (`critical` → "Within
    48 h", else "This week"), "Needs attention" (next dates to review, recent order next dates, compliance due soon
    and overdue, open transfers), custody by office; a section the API returns as `null` is not shown. Personal block:
    own cases per department, files held with pending action and overdue, own alerts, own hearings, drafts. State
    block: the per-department table (claimed, recommended, hearings in 7 days, pending and overdue files,
    compliance), the not-claimed row, hearings across the State, overdue files. Counts only as the API gives them;
    the portal computes nothing. A login without `cases.view_scope` / `cases.view_all` sees a short page pointing
    to the screens it does have.
15. **Administration screens** (each action shown only with its function; the API's codes become messages):
    - Users (`/admin/users`): search by name or e-mail, filter by office subtree and user type, paged 50 at a time;
      the super admin also sees logins with no active membership (to re-enable them). New user (`users.create`):
      e-mail, name, temporary password (the API forces a change), the first membership (office, designation, type);
      before creating, an exact e-mail lookup offers "add a membership to this person" instead of a duplicate.
    - User detail (`/admin/users/[id]`): login (name, e-mail correction, mobile; `users.edit`), enable / disable
      (`users.enable_disable`), set a temporary password (`users.reset_password`), memberships (add `users.create`;
      change designation or type `users.edit` / `users.set_type`; make primary `users.edit`; end with the **exit
      dialog** — the API's preview of allotments and held files, a successor chosen for each item, then end — and
      reactivate, `users.enable_disable`), each membership's functions with its grant / deny overrides and reason
      (`users.grant`; the API refuses functions the caller does not hold and `admin.tickets`), and the
      government-order documents of a membership (`users.propose_head` / `admin.tickets`).
    - User types and functions (`/admin/access`): the type × function matrix by module; switching a cell needs
      `access.manage_types` (the super admin), others read it with `users.view`.
    - Offices (`/admin/offices`, `/admin/offices/[code]`): the tree with active-user counts; create (kind and parent
      as the placement rules allow, the API refuses the rest), edit, deactivate (the API's dependency counts shown on
      409), reactivate (`offices.manage`); the department admin and head shown; first department admins and the admin
      swap (super admin; `users.create`).
    - Designations (`/admin/designations`): list for everyone signed in; create, edit, deactivate, reactivate with
      `admin.designations`.
    - Tickets (`/admin/tickets`, `/admin/tickets/[ref]`, the mail-link path): open / approved / rejected / withdrawn
      / all, counts; propose a head change (`users.propose_head`), approve or reject (super admin), withdraw (the
      proposer), attach a government order (PDF, Word or image, the API's scan and limit), download, archive. `[ref]`
      accepts the `-` form of the mail links.
    - My profile (`/profile`): name and mobile, notification preferences, password change (through the session
      handler, decision 6), devices with "sign out this device".
16. **Small API additions, no schema change.** (a) `GET /reference/labels`: the labels of user types, office kinds
    and ticket kinds from `ref_role`, `ref_office_kind`, `ref_ticket_kind`, each user type with `assignable` for the
    caller (super admin: every type but `super_admin`; a holder of `users.create` or `users.set_type`: the delegable
    types; otherwise none), so the portal shows labels from the database instead of a copy and offers only types the
    server would accept (the server still decides). (b) `GET /admin/users` gains `q`, `role`, `include_ended`,
    `limit` (1–200), `offset`, and an `X-Total-Count` header; without `limit` it answers as today (all rows), so
    existing callers keep working. Alternatives: client-side filtering of the full list (every login with its
    memberships, one query per login, for the whole State).
17. **Look and accessibility.** Plain CSS with CSS Modules and design tokens in `globals.css` (colours, spacing,
    type scale from Annexure B); no UI framework. Fonts self-hosted from npm packages (`@fontsource` Source Serif 4,
    IBM Plex Sans, IBM Plex Mono) so the portal makes no request outside its own origin. Target WCAG 2.1 AA (the
    level GIGW 3.0 asks of government sites): labelled fields, keyboard use, visible focus, `aria-live` errors,
    contrast checked on the tokens. English only; every user-facing string sits in `src/lib/messages.ts`, so another
    language can be added later. Dates shown in IST (`Asia/Kolkata`) as `25 Sep 2026`, whatever the browser's zone.
18. **Security headers.** Set by `proxy.ts` on every page: a CSP with a per-request nonce
    (`default-src 'self'; script-src 'self' 'nonce-…' 'strict-dynamic'; style-src 'self' 'unsafe-inline';
    img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'`),
    `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Permissions-Policy` denying camera,
    microphone and geolocation; `poweredByHeader: false`; telemetry off (`NEXT_TELEMETRY_DISABLED=1`). The web server
    logs method, path, status and duration only, never bodies, cookies or tokens.
19. **API types from the API.** `backend/tools/export_openapi.py` writes `frontend/openapi.json` from
    `create_app().openapi()`; `npm run gen:api` turns it into `frontend/src/lib/api/schema.d.ts`
    (`openapi-typescript`); both are committed. A pytest test fails when the committed `openapi.json` differs from
    the app's, so a backend change that alters the contract regenerates the types in the same change.
20. **Compose `web` service.** Built from `frontend/Dockerfile` (multi-stage `node:22-alpine`, `output:
    "standalone"`, runs as the `node` user on port 3000, health check on `GET /api/health`, which answers without
    calling the API). It gets only `API_BASE_URL=http://api:8000`, `PORTAL_BASE_URL`, `COOKIE_SECURE`,
    `ASLMS_REFRESH_TOKEN_DAYS`, `RELAY_TIMEOUT_SECONDS` — **no `env_file`**, so no secret (JWT secret, NAPIX or mail
    credentials) ever enters the web container. Port `${WEB_HOST_PORT:-3000}`, matching the default
    `PORTAL_BASE_URL`. `api` gains a health check on `/health`; `web` depends on `api` being healthy. No `.env` file
    in `frontend/` (the guard blocks `.env.*`); local `npm run dev` defaults to `http://localhost:8000`.
21. **Frontend checks join the definition of done.** In `frontend/`: `npm run lint` (ESLint, Next config),
    `npm run typecheck` (`tsc --noEmit`), `npm test` (Vitest + Testing Library + jsdom), `npm run build`; the
    integrator also runs `docker compose build web`. The scribe adds the line to `docs/team/definition-of-done.md`.

No deviation from the plan: every module the plan lists stays; this item delivers the shell, sign-in, dashboard and
administration and leaves the other screens to their rows.

## Data
No table, column, reference code or `Permission` is added; no migration. `docs/schema/schema.md` is unchanged. The
portal stores nothing server-side apart from the in-memory refresh map of decision 4 (lost on restart, which costs
nothing: the cookie still holds the current refresh token).

## Services
Backend (Python):
- `backend/aslms/services/reference.py` (new): `labels(session, user) -> dict` reading `ref_role`,
  `ref_office_kind`, `ref_ticket_kind` (active rows, `sort_order`), and `assignable_types(session, user) ->
  set[Role]` from `access.is_super_admin`, `access.has(users.create | users.set_type)` and
  `access.DELEGABLE_ROLES`. Reads only; no audit row (reading reference data is not a significant action).
- `backend/aslms/api/routers/users.py::list_users`: the filters of decision 16(b) in SQL (`q` ILIKE on
  `full_name` and `email`, at least 2 characters else 400 `bad_field`; `role` on an active membership; `include_ended`
  only when `_scope_roots` is `None`, else 403 `{code: "scope"}`, using an outer join so logins without an active
  membership appear; `limit` / `offset`; `X-Total-Count` from a count over the same filters). The scope rule is
  unchanged.
- `backend/tools/export_openapi.py` (new): writes the OpenAPI JSON (sorted keys, 2-space indent, trailing newline).

Frontend (`frontend/`):
- `src/server/session.ts`: cookie names, flags and lifetimes (decision 3); `setTokens`, `clearSession`
  (keeps `aslms_device`), `readSession`.
- `src/server/refresh.ts`: the single-flight refresh with the 30-second remembered result (decision 4).
- `src/server/relay.ts`: path checks, denylist from `token-routes.json`, header allowlists, `X-Forwarded-For`,
  streaming, timeout, the one retry after refresh (decisions 5–7).
- `src/server/csrf.ts`: the `X-ASLMS-Request` and `Origin` checks.
- `src/app/api/session/*` route handlers: `login`, `verify`, `resend`, `reset/request`, `reset/confirm`,
  `password`, `logout`; `src/app/api/backend/[...path]/route.ts` (the relay); `src/app/api/health/route.ts`.
  The session handlers return the API's step data without `challenge_id` (kept in `aslms_challenge`) and never a
  token; `logout` revokes the refresh token at the API (refreshing first if the access token has expired) and clears
  the session cookies even if the API is unreachable.
- `src/proxy.ts`: page gate and security headers (decisions 10, 18).
- `src/lib/api/client.ts`: the fetch wrapper (adds `X-ASLMS-Request`, parses the three error shapes into
  `{status, code, message, extra}`, handles `signed_out` and the gate codes), `schema.d.ts` (generated).
- `src/lib/routes.ts`, `src/lib/can.ts` (`can(me, fn)`), `src/lib/messages.ts` (codes → text, server message as
  fallback), `src/lib/format.ts` (IST dates, numbers in the Indian grouping `1,28,400`), `src/lib/safeNext.ts`.
- `src/components/ui/*` (Button, Field, Select, Table, Tabs, Badge, Dialog, Tile, EmptyState, ErrorBanner,
  Pagination), `src/components/shell/*`, `src/components/dashboard/*`, `src/components/admin/*`.
- Pages: `(public)/login`, `login/code`, `forgot`, `forgot/code`; `(welcome)/welcome/password`, `welcome/profile`;
  `(portal)/page.tsx` (dashboard), `profile`, `admin/users`, `admin/users/new`, `admin/users/[id]`, `admin/access`,
  `admin/offices`, `admin/offices/new`, `admin/offices/[code]`, `admin/designations`, `admin/tickets`,
  `admin/tickets/new`, `admin/tickets/[ref]`; `not-found`, `error`.

Audit and events: the portal writes none itself; every action it offers is an API call that already audits
(`auth.*`, `user.*`, `membership.*`, `access.*`, `office.*`, `designation.*`, `ticket.*`, `profile.*`).

## API
New or changed (FastAPI):

| Method, path | Function required | Request | Response | Visibility |
|---|---|---|---|---|
| `GET /reference/labels` | signed in, gate not applied (`current_user_pending`, used by `/welcome/profile`); no function | — | `{user_types: [{code, label, description, assignable}], office_kinds: [{code, label}], ticket_kinds: [{code, label}]}` | reference data, the same for everyone except `assignable` |
| `GET /admin/users` (changed) | `users.view` (unchanged) | `office?`, `q?` (≥ 2 chars), `role?`, `include_ended?` (scope `None` only), `limit?` 1–200, `offset?` ≥ 0 | `list[UserOut]` as today; header `X-Total-Count` | the caller's `_scope_roots` (unchanged); 403 `scope` for `include_ended` outside State-wide scope; 400 `bad_field` for a short `q` or bad paging |

Web server (Next.js) endpoints, for the browser only; each calls the named API endpoint, which applies its own
function and visibility rules:

| Method, path | Calls | Function | Notes |
|---|---|---|---|
| `POST /api/session/login` | `POST /auth/login` | none (public) | sends `device_token` from `aslms_device` and a short device label from the user agent; sets `aslms_challenge`; returns `{step, sent_to, expires_in, resend_after}` or the API error |
| `POST /api/session/verify` | `POST /auth/otp/verify` | none | sets `aslms_at`, `aslms_rt`, `aslms_device` (if issued); clears `aslms_challenge`; returns `{next_step, user}` |
| `POST /api/session/resend` | `POST /auth/otp/resend` | none | uses `aslms_challenge` |
| `POST /api/session/reset/request` | `POST /auth/password-reset/request` | none | always 202 as the API; sets `aslms_challenge` |
| `POST /api/session/reset/confirm` | `POST /auth/password-reset/confirm` | none | 204; clears `aslms_challenge` and session cookies |
| `POST /api/session/password` | `POST /me/password` | signed in (`current_user_pending`) | replaces the token cookies; returns `{next_step}` |
| `POST /api/session/logout` | `POST /auth/logout` | signed in | clears session cookies, keeps `aslms_device` |
| `GET\|POST\|PUT\|PATCH\|DELETE /api/backend/{path}` | `/{path}` | the API endpoint's own | decisions 5–7; denylist 404 |
| `GET /api/health` | — | none | `{status: "ok"}` |

All non-GET web endpoints require `X-ASLMS-Request: 1` and a matching `Origin` (403 `csrf`).

## Jobs
None. (The alert count in the header is a browser poll every 2 minutes through the relay, not a server job.)

## Tests
Backend (pytest, `backend/tests/`):
- `db/test_api_reference.py`: `test_labels_lists_every_user_type_with_its_label`;
  `test_labels_office_and_ticket_kinds`; `test_assignable_super_admin_every_type_but_super_admin`;
  `test_assignable_delegated_holder_only_delegable_types`; `test_assignable_officer_none`;
  `test_labels_signed_out_401`; `test_labels_answer_during_first_sign_in_gate`.
- `db/test_api_users_list.py`: `test_q_matches_name_and_email`; `test_q_too_short_400`; `test_role_filter`;
  `test_limit_offset_and_total_header`; `test_no_limit_answers_all_as_before`;
  `test_include_ended_super_admin_sees_logins_without_membership`; `test_include_ended_department_admin_403`;
  `test_filters_never_widen_scope` (a department admin's `q` matching another department's login returns nothing,
  `X-Total-Count` 0).
- `unit/test_openapi_snapshot.py`: `test_committed_openapi_matches_the_app`.
- `unit/test_token_routes.py`: `test_every_operation_returning_tokens_is_listed` (every response schema with
  `access_token`, `refresh_token` or `device_token` is in `frontend/src/server/token-routes.json`, and nothing else
  is).
- `unit/test_compose_web.py`: `test_web_service_has_no_env_file`; `test_web_api_base_url_is_the_api_service`;
  `test_api_trusts_forwarded_headers_only_from_web_ip`; `test_web_depends_on_healthy_api`.

Frontend (Vitest, `frontend/src/**/*.test.ts(x)`):
- `server/session.test.ts`: cookie flags (HttpOnly, SameSite=Lax, Secure by `COOKIE_SECURE`, paths, lifetimes from
  `expires_in` and the refresh days); `clearSession` keeps the device cookie.
- `server/refresh.test.ts`: two concurrent requests with an expired access token make one `/auth/refresh`;
  a request with the old refresh token inside 30 s gets the remembered pair and makes no call; after 30 s the
  entry is gone; `session_ended` and `refresh_invalid` clear the cookies and give 401 `signed_out`.
- `server/relay.test.ts`: adds `Authorization` from the cookie; never forwards browser cookies, `Authorization` or
  `X-Device-Token`; never returns `Set-Cookie`; header allowlists both ways incl. `X-Total-Count` and
  `Content-Disposition`; denylisted paths, `..`, encoded slash, `//` → 404; one retry after a 401 then 401
  `signed_out`; streaming of a multipart body; timeout → 502 `api_unavailable`; `no-store` added.
- `server/csrf.test.ts`: non-GET without the header → 403; foreign `Origin` → 403; same origin with header → passes;
  GET passes.
- `app/api/session/*.test.ts`: no response body contains a token or the challenge id; verify sets the three cookies
  and returns `next_step`; logout clears cookies when the API is down; reset request is a neutral 202.
- `lib/api/client.test.ts`: parses `{code, message}`, a string `detail` and the 422 list; gate codes redirect to the
  welcome pages; `signed_out` clears the query cache and goes to `/login?next=`.
- `lib/safeNext.test.ts`: `//evil`, `https://…`, `/\evil`, empty → `/`; `/admin/users` kept.
- `lib/format.test.ts`: IST dates for a UTC instant near midnight; Indian digit grouping.
- `components/auth/*.test.tsx`: password step → code step; resend disabled until `resend_after`; `attempts_left`
  shown; `locked` shows the wait; `next_step` routing; first-sign-in password form shows the policy and the server's
  `weak_password` message; profile confirm requires the mobile number.
- `components/shell/*.test.tsx`: navigation by functions (an officer sees no Administration; a department admin
  sees Users and Offices but not the type-matrix switches; unbuilt entries hidden); alert badge from `/alerts/counts`;
  memberships list in the sidebar foot.
- `components/dashboard/*.test.tsx`: blocks chosen by `/dashboard`; a department selector with two departments;
  `null` sections not rendered; one failing block shows its error while others render; the 48-hour badge from
  `critical`; the no-dashboard page for a login without case functions.
- `components/admin/*.test.tsx`: action buttons by function on the user detail; the exit dialog shows every preview
  item and does not submit until each has a successor; the e-mail lookup offers "add a membership"; offering only
  `assignable` types; matrix cells read-only without `access.manage_types`; ticket approve / reject only for the
  super admin, withdraw only for the proposer; office deactivate shows the 409 counts.

## Verification
1. `backend/.venv/Scripts/ruff check backend` and `backend/.venv/Scripts/python -m pytest -q` green (the new tests
   included); `python backend/tools/export_openapi.py` leaves `git diff --exit-code frontend/openapi.json` clean.
2. In `frontend/`: `npm ci`, `npm run gen:api` (no diff), `npm run lint`, `npm run typecheck`, `npm test`,
   `npm run build` all pass. (The developer needs `npm` commands approved in the session; the owner adds them to the
   allow list if wanted.)
3. `docker compose build web api` and `docker compose up -d`; `docker compose ps` shows `web` and `api` healthy;
   `curl -s http://localhost:3000/api/health` → `{"status":"ok"}`; `curl -s -o /dev/null -w "%{http_code}"
   http://localhost:3000/api/backend/me` → 401; `.../api/backend/auth/refresh` and `.../api/backend/openapi.json` → 404;
   `curl -X POST http://localhost:3000/api/backend/admin/users -d '{}'` (no `X-ASLMS-Request`) → 403.
4. `docker compose exec web env` lists no `ASLMS_JWT_SECRET`, `NAPIX_*`, `MAILTRAP_*` or `SMTP_*` variable.
5. With the Mailtrap sandbox (or `MAIL_BACKEND=console` in development, the code read from `docker compose logs
   api`), sign in at `http://localhost:3000/login` as the seeded super admin: the code page, then the forced password
   change, the profile confirmation, then the dashboard with the personal and State blocks. Browser dev tools: the
   cookies are HttpOnly; no response body under `/api/session` or `/api/backend` contains `access_token` or
   `refresh_token`.
6. As the super admin: create a department admin for an existing department (offices screen), sign in as that admin
   in a private window, create an officer, open the officer's detail and grant one held function; the audit log
   (`aslms audit search --limit 10`) shows `user.created`, `access.*` rows whose `ip` is the browser host's address,
   not `172.28.0.10`.
7. Reload the dashboard after 31 minutes (or with `aslms_at` deleted in dev tools): the blocks load, and the API log
   shows exactly one `/auth/refresh` for the reload.
8. Open a ticket mail link of the form `/admin/tickets/TKT-…` signed out: redirected to sign-in, then back to the
   ticket.

## Open questions
None.
