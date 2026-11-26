# Design: ASLMS API reference

```
slug: api-reference
status: approved
author: main session (from the owner's instructions)
date: 2026-11-26
approved_by: owner on 2026-11-26
```

## Context
Backlog row 283. On 26 Nov 2026 the owner asked for "something like an openAPI docs for ASLMS own APIs because
these are the only APIs that i have created". The NAPIX APIs are the e-Committee's and are not documented again:
the specifications in `docs/specs/` and `docs/napix_integration_notes.md` stay their reference, and the ASLMS
reference only marks which ASLMS endpoints can call the court.

Today FastAPI already generates an OpenAPI document (`backend/tools/export_openapi.py` writes
`frontend/openapi.json`, 275 operations in 26 tags, checked by `test_openapi_snapshot`), but as documentation it is
thin: summaries are function names ("List Queue"), the 207 descriptions are developers' notes citing design
decisions ("Stop Using Everything (decision 31): …") and 68 have none, the function an endpoint needs is not stated
(107 routes use `require` / `require_any`; the rest check functions or membership inside services), only 114 list
their error answers, and sign-in is not explained. `/docs`, `/redoc` and `/openapi.json` are served only when
`APP_ENV=dev` (deployment checklist, decision 4) and stay so.

The owner chose (26 Nov 2026): the recommended reference, **plus a Word copy**, and the build **next after row 281**,
before row 252.

## Decisions
1. **Every operation reads as documentation.** Each route gets a written `summary` (a short action in Title Case,
   e.g. "Stop a Data Collection Request") and a plain `description` for an outside reader: what it does, who may
   call it, what it changes, paging and filters where they apply. The developers' notes and design-decision
   references move from docstrings to code comments, so none appears in the reference. Wording follows the portal's
   rules (plain words, no eOffice vocabulary, no agency names, no personal names).
2. **Groups.** The 26 tags get `openapi_tags` entries with a description each, in a reader's order (Sign-In and
   Profile first, then Cases, Case Inbox, Ownership, Workflow, Documents, Alerts, Next Dates, Cause Lists, Assistant,
   Dashboard, Reports, Insights, then the administration and operations groups). Tag names are shown in words;
   paths and codes are unchanged.
3. **Who may call it.** Every operation carries `x-aslms-access` (via `openapi_extra`) naming the functions it needs
   (`["cases.view_scope", "cases.view_all"]`, "any of"), or `signed-in` (any signed-in login past the first-sign-in
   gate), or `public` (sign-in steps, health). The description repeats it in words ("Requires the function
   Data Collection (`admin.data_load`)"). For routes using `require` / `require_any` a test checks the extension
   equals the dependency's functions; for checks inside services the developer reads the service and records it,
   noting membership or visibility rules in words ("returns only cases the caller may open").
4. **Court calls.** Operations that can call NAPIX carry `x-aslms-court-call: true` and a line in words: that the
   call counts against the hourly allowance, may answer 503 `napix_busy`, and is answered from held data first where
   that is so. The list is checked by a test against the routes that reach `backend/aslms/integration/napix/`.
5. **Errors.** Each operation lists its error answers (400, 403, 404, 409, 503 and others it can return) with the
   `code` values it can give, using one shared error schema `{code, message, ...}` from `api/errors.py`. A reference
   section explains the format, 401 and token renewal, the first-sign-in 403 codes, 422 validation, and that a
   resource the caller may not see answers 404.
6. **Conventions section** (the OpenAPI `info.description`): signing in (password, then the e-mailed six-digit code,
   then the bearer token; refresh; session time-out after 30 minutes without activity and 12 hours in all), the
   portal's backend-for-frontend keeping tokens in httpOnly cookies, server-side visibility, paging (`limit`,
   `offset`, `total`), the shared case filters and `q` / `sort` with `bad_sort`, dates and times in IST, ASLMS
   reference numbers versus CNRs, and that nothing is ever deleted (append-only records).
7. **Examples.** Request and response examples for the main reader and action endpoints (sign-in, case search, case
   detail, claim, send file, add note, upload, ask the Assistant), with sample data that cannot be mistaken for a
   held case (masked case numbers such as `WP(C)/XXXX/2026`, no CNR, no real names), as row 281 decision 4.
8. **Outputs.**
   - `docs/api/openapi.json`: the same document as `frontend/openapi.json`, for tools such as Postman.
   - `docs/api/ASLMS_API_Reference.html`: one self-contained HTML file built from it, opening offline with no
     request to any server (a ReDoc-style reference; the generator pinned to an exact version at least two weeks
     old, its script and styles inlined).
   - `docs/ASLMS_API_Reference.docx` (owner's choice): the Word copy for submission beside the software
     documentation, generated from the same document by a script in `docs/api/` with the `docx` package, as
     `docs/software-documentation/build.js` is: a cover, the conventions, then each group with its endpoints
     (method, path, purpose, access, court call, parameters, request and response fields, errors); text only.
   - `docs/api/README.md`: how to regenerate all three.
9. **No behaviour change.** Paths, methods, parameters, schemas, status codes and permission checks stay exactly as
   they are; only metadata, docstrings and comments change. `/docs` stays development-only.

## Data, Services, API, Jobs
None changed. No migration. `frontend/openapi.json` and `schema.d.ts` are regenerated (descriptions only; the
generated types must not change shape).

## Tests
- `test_openapi_docs.py`: every operation has a tag listed in `openapi_tags`, a summary that is not the
  function-name default, a description of at least a sentence with no `decision \d+` / design-slug references, and
  `x-aslms-access`; routes with `require` / `require_any` match their extension; court-call marks match the routes
  that reach the NAPIX layer; every listed error has a `code`.
- `test_openapi_snapshot` still passes after regeneration; a check that `docs/api/openapi.json` equals the snapshot.
- A check that the HTML file makes no external request (no `http(s)://` script, link or font source) and that the
  Word build runs.
- Full pytest and vitest; `schema.d.ts` shape unchanged (frontend typecheck green with no code change).

## Verification
1. `ruff check`, `pytest -q`, frontend lint, typecheck and tests green.
2. The owner opens `docs/api/ASLMS_API_Reference.html` and `docs/ASLMS_API_Reference.docx` and reads a few groups.

## Open questions
None. The owner's choices of 26 Nov 2026 settle the scope.
