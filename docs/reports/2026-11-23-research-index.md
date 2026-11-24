# Report: research-index (row 251)

Merged 24 Nov 2026 from `feature/research-index` by squash into `main`, tag `feature/research-index-done`.

## What changed
- Meaning search for research: embeddings from the local Ollama model `embeddinggemma:300m` through
  `backend/aslms/integration/ollama/`, stored with pgvector (HNSW index) in PostgreSQL.
- Postgres image `aslms/postgres:16.15-pgvector0.8.7` (`infra/postgres/Dockerfile`).
- Migration 0042 (`research_chunks`, `research_embeddings`, case sheets, extension `vector`).
- Chunks cut from row 250's order readings plus one case sheet per case; hybrid retrieval (words and meaning lists,
  reciprocal rank fusion, small-to-big) for All Court Orders, My Cases and related orders.
- Server-side sentence checks of local-model answers; filters refused when the index does not serve the question
  (`filters_unavailable`); 5-minute embedding job and 01:45 reconcile; `aslms research-index`; `RESEARCH_*` settings.
- Frontend: generated API types, enum labels and messages only (the screens are row 275). Runbook section 28.

## Gates
- `ruff check .`: all checks passed.
- `pytest -q` on a throwaway container of the branch's own pgvector image (port 7433, removed afterwards),
  `ASLMS_TEST_REQUIRE_DB=1`: 3944 passed, 3 skipped, 1:16:03. The 3 skips are not database tests (a hand-saved
  encrypted envelope, symbolic links and POSIX permissions, unavailable on Windows).
- `docker compose build`: succeeded (no `up`).
- Screen check on a private network with a `web` image from the branch: 195 routes and states, 638 screenshots,
  0 findings. Container, network and images removed.
- CI on main before the merge: last run success (Approve design: research-index).
- Design status `approved`; decisions-log entry and backlog row 251 present.

## Review findings
The four blocking findings were fixed before merge (HNSW order without the second key, sheet keyset cursor,
orphan sets retired only after the new sets are cut, filters refused when the index will not serve the question;
commits b9c5efb and 619be15). The advisories were not closed and are in row 277.

## Deviations
None found by the integrator beyond those recorded in the design note (deviations 15 to 17 included).

## Follow-up rows
- 277 `research-index-advisories` (19 points).
- 275 `research-index-portal` and 276 `research-index-docs` already existed.

## Load status
`aslms queue-status` did not answer within 120 s on this host (the dev database's published port was not
reachable); not recorded.
