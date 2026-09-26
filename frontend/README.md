# ASLMS v2 portal (frontend)

The web portal of the Legal Case Monitoring Portal (Gauhati High Court), Government of Assam. Next.js 15
(App Router), React 19, TypeScript (strict), plain CSS with CSS Modules. It talks only to the ASLMS FastAPI
backend (`backend/`), through its own server.

## Run

```bash
cd frontend
cp .env.example .env.local      # set API_BASE_URL if the backend is not on http://localhost:8000
npm install
npm run dev                     # http://localhost:3000
```

Checks (all must pass before a change is merged):

```bash
npm run typecheck               # tsc --noEmit
npm run lint                    # eslint (next/core-web-vitals + next/typescript)
npm run build                   # production build, standalone output
```

Regenerate the API types after the backend contract changes (export `openapi.json` from the backend first):

```bash
npm run gen:api                 # openapi.json -> src/lib/api-types.ts
```

## Docker

```bash
docker build -t aslms-portal ./frontend
docker run --rm -p 3000:3000 -e API_BASE_URL=http://api:8000 aslms-portal
```

The image runs `node server.js` from the standalone output as a non-root user on port 3000. Put it behind the
nginx reverse proxy with TLS; the session cookies are `Secure` in production.

## Environment

| Variable        | Default                 | Meaning |
|-----------------|-------------------------|---------|
| `API_BASE_URL`  | `http://localhost:8000` | Backend base URL as reached from the portal server (server-side only, never sent to the browser). In compose: `http://api:8000`. |
| `COOKIE_SECURE` | (unset)                 | Session cookies are `Secure` when `NODE_ENV=production`. Set `false` only for a closed-network pilot served over plain HTTP; `true` forces it on. |
| `PORT`, `HOSTNAME` | `3000`, `0.0.0.0`    | Listening address of the standalone server (set in the Dockerfile). |

## How sign-in and API access work

The portal is a backend-for-frontend: tokens never reach browser JavaScript.

1. `/login` posts e-mail and password to `POST /api/auth/login`, which forwards to the backend and returns the
   OTP challenge id. The six-digit OTP goes to `POST /api/auth/verify`; on success the portal server sets two
   httpOnly, SameSite=Lax cookies: `aslms_at` (access token, expires with the token) and `aslms_rt` (refresh
   token, 14 days). `/api/auth/logout` revokes the refresh token at the backend and clears both;
   `/api/auth/forgot` and `/api/auth/reset` handle a forgotten password.
2. The browser calls `/api/v1/...` on the portal. The catch-all handler `src/app/api/v1/[...path]/route.ts`
   forwards the request to `${API_BASE_URL}/api/v1/...` with `Authorization: Bearer <access token>`, streaming
   uploads and downloads both ways and keeping `Content-Type` / `Content-Disposition`. The browser's cookies
   are never forwarded. Paths containing `..` are refused, and `/api/v1/auth/*` is not proxied.
3. When the access cookie has expired, or the backend answers 401, the handler refreshes once with the refresh
   cookie, sets both new cookies and retries. Concurrent refreshes that present the same refresh token share a
   single backend call, because the backend treats the reuse of a rotated refresh token as theft and ends
   every session of the user.
4. Mutating requests must carry `X-Requested-With: aslms` (added by `src/lib/api.ts`) and a same-site
   `Origin`; with SameSite cookies this blocks cross-site request forgery.
5. `src/middleware.ts` sends visitors without a refresh cookie to `/login?next=...`. `/login`, `/forgot`,
   static assets and `/api/*` are not redirected (API routes answer 401 themselves).

Visibility is enforced by the backend in SQL. The portal only hides what a role cannot use: navigation items,
write buttons for read-only roles (state oversight, auditor), claim/transfer/allot for non-department roles.

## Layout

```
src/
  middleware.ts                 sign-in redirect
  app/
    layout.tsx, globals.css     fonts (self-hosted via @fontsource), design tokens
    (public)/login, forgot      sign-in with OTP, password reset
    (portal)/                   the signed-in portal (shell: nav, header, search, notifications)
      page.tsx                  dashboard (role-aware)
      welcome, inbox, search, cases/[id], alerts, notifications, causelists, reports, admin, audit, settings
    api/auth/*                  login, verify, logout, forgot, reset (BFF)
    api/v1/[...path]            authenticated proxy to the backend
  components/
    ui/                         buttons, pills, cards, fields, tabs, dialog, toasts, tables, pagination
    shell/                      app shell, notification bell, signed-in user context
    case/                       tracking cards, hearing rows, signals; detail/ for the case page tabs
    inbox/ dashboard/ alerts/ reports/ admin/ settings/
  lib/
    api-types.ts                generated from openapi.json (do not edit)
    types.ts                    type aliases, plus shapes the OpenAPI document leaves untyped
    api.ts                      browser API client (typed errors, redirect on 401)
    server/                     BFF session and relay helpers (server-only)
    format.ts                   DD Mon YYYY dates, IST times, Indian number grouping
    roles.ts labels.ts hooks.ts urlState.ts safeNext.ts
```
