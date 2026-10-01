# ASLMS v2 — Assam State Legal Management System

Legal Case Monitoring Portal for the Government of Assam: every department tracks its cases before the Gauhati
High Court in one place, acts on court directions in time, and keeps an accountable record of how each case is
handled. Data comes from the official eCourts / High Court APIs (NAPIX); case research and order reading go
through SourceTrace, the in-house RAG service.

## State of the repository (1 Oct 2026)

The system is being rebuilt from the approved documents after a full reset. The September 2026 build is kept
outside the workspace as reference (`D:\Dev Workspace\ASLMS-legacy\v3-sept-build`). This repository currently
holds the documents only; the code returns module by module, starting with the NAPIX integration layer.

| Document | Purpose |
|---|---|
| `docs/Legal_Case_Monitoring_Portal_Plan.docx` | The agreed plan. Source of truth. |
| `docs/claude_ASLMS_design_decisions.md` | Decision log and open points. |
| `docs/DB_STANDARD.md`, `docs/schema/schema.md` | The database standard and the approved design. |
| `docs/napix_integration_notes.md`, `docs/napix_integration_design.md` | How NAPIX behaves live, and the integration layer's design. |
| `docs/specs/napix/hc/`, `docs/specs/samples/`, `docs/postman/` | NAPIX gateway stubs, decrypted live samples, the Postman collection. |
| `CLAUDE.md` | Working rules for anyone (or any agent) changing code here. |

The database starts empty. There is no migration of earlier data.

## Next

1. NAPIX integration layer and the live `aslms napix-check` (settles the open endpoint questions, saves samples,
   builds the field inventory).
2. Schema addendum mapping every NAPIX field; migration 0001; seed; Docker Compose.
3. The plan's build order: daily cycle, recommend-and-claim, authentication, documents, alerts, portal.

`.env.example` documents every variable; copy it to `.env` and fill the NAPIX credentials for the live test.
