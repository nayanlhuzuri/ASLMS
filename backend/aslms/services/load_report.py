"""Load counts and the sample-of-20 CNR check (design deployment-checklist, decision 19). Read-only; no NAPIX call.

- `report(session)`: the period held, cause-list days, cases, dossiers, parties, advocates, orders, documents with text,
  NAPIX calls, `fetch_queue` by lane and status, open `source_failures`, database size and the store's files.
- `sample(session, pending, disposed, seed)`: a reproducible draw (`ORDER BY md5(cnr || seed)`) of cases with a CNR and
  an applied dossier, with the fields an operator compares by hand against the court's public case status. Two blank
  columns follow ("court shows", "match")."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from aslms.services.backups import store_totals


def _one(session: Session, sql: str, **params: Any) -> Any:
    return session.execute(text(sql), params).one()


def _scalar(session: Session, sql: str, **params: Any) -> Any:
    return session.execute(text(sql), params).scalar()


def report(
    session: Session, *, store_dir: str | Path | None = None, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    first, last = _one(session, "SELECT min(list_date), max(list_date) FROM causelists")
    days = dict(
        zip(
            ("loaded", "skipped", "failed", "pending"),
            _one(
                session,
                """SELECT count(*) FILTER (WHERE status = 'done'), count(*) FILTER (WHERE status = 'skipped'),
                          count(*) FILTER (WHERE status = 'failed'),
                          count(*) FILTER (WHERE status IN ('pending', 'running'))
                   FROM fetch_queue WHERE kind = 'causelist_day'""",
            ),
        )
    )
    days["list_pdfs_stored"] = _scalar(
        session, "SELECT count(*) FROM causelists WHERE document_id IS NOT NULL"
    )
    days["entries"] = _scalar(session, "SELECT count(*) FROM causelist_entries")
    cases = dict(
        zip(
            ("total", "with_cnr", "provisional_with_cnr", "provisional_without_cnr", "pending", "disposed"),
            _one(
                session,
                """SELECT count(*), count(*) FILTER (WHERE cnr IS NOT NULL),
                          count(*) FILTER (WHERE is_provisional AND cnr IS NOT NULL),
                          count(*) FILTER (WHERE is_provisional AND cnr IS NULL),
                          count(*) FILTER (WHERE status = 'pending'), count(*) FILTER (WHERE status = 'disposed')
                   FROM cases WHERE merged_into_case_id IS NULL""",
            ),
        )
    )
    dossiers = {
        "applied": _scalar(
            session,
            "SELECT count(*) FROM cases WHERE merged_into_case_id IS NULL AND last_full_refresh_at IS NOT NULL",
        ),
        "failed": _scalar(
            session, "SELECT count(*) FROM fetch_queue WHERE kind = 'dossier' AND status = 'failed'"
        ),
        "never_fetched": _scalar(
            session,
            """SELECT count(*) FROM cases c WHERE c.merged_into_case_id IS NULL AND c.cnr IS NOT NULL
                   AND c.last_full_refresh_at IS NULL
                   AND NOT EXISTS (SELECT 1 FROM fetch_queue q
                                   WHERE q.kind = 'dossier' AND q.ref = c.cnr AND q.status = 'failed')""",
        ),
    }
    orders = dict(
        zip(
            ("references", "pdfs_stored", "pdfs_pending", "pdfs_not_available", "pdfs_failed"),
            _one(
                session,
                """SELECT count(*), count(*) FILTER (WHERE document_id IS NOT NULL),
                          count(*) FILTER (WHERE document_id IS NULL AND download_status = 'pending'),
                          count(*) FILTER (WHERE document_id IS NULL AND download_status = 'not_available'),
                          count(*) FILTER (WHERE document_id IS NULL AND download_status = 'failed')
                   FROM orders""",
            ),
        )
    )
    since = now - timedelta(days=7)
    calls_total, calls_7d = _one(
        session,
        "SELECT count(*), count(*) FILTER (WHERE called_at >= :since) FROM napix_call_log",
        since=since,
    )
    by_outcome = {
        str(k): int(n)
        for k, n in session.execute(
            text(
                """SELECT CASE WHEN ok THEN 'ok' ELSE coalesce(error_family, 'error') END AS outcome, count(*)
                   FROM napix_call_log GROUP BY 1 ORDER BY 1"""
            )
        ).all()
    }
    queue = [
        {"lane": str(lane), "status": str(status), "rows": int(n)}
        for lane, status, n in session.execute(
            text("SELECT lane, status, count(*) FROM fetch_queue GROUP BY lane, status ORDER BY lane, status")
        ).all()
    ]
    failures = {
        str(k): int(n)
        for k, n in session.execute(
            text(
                "SELECT kind, count(*) FROM source_failures WHERE resolved_at IS NULL GROUP BY kind ORDER BY kind"
            )
        ).all()
    }
    files, size = store_totals(Path(store_dir)) if store_dir else (0, 0)
    return {
        "as_of": now.isoformat(),
        "period": {"first_list_date": first, "last_list_date": last},
        "causelist_days": {k: int(v) for k, v in days.items()},
        "cases": {k: int(v) for k, v in cases.items()},
        "dossiers": {k: int(v) for k, v in dossiers.items()},
        "parties": int(_scalar(session, "SELECT count(*) FROM case_parties")),
        "advocates": int(_scalar(session, "SELECT count(*) FROM case_advocates")),
        "orders": {k: int(v) for k, v in orders.items()},
        "documents_with_text": int(
            _scalar(session, "SELECT count(*) FROM documents WHERE text_status = 'extracted'")
        ),
        "napix_calls": {
            "total": int(calls_total),
            "by_outcome": by_outcome,
            "per_day_last_7_days": round(int(calls_7d) / 7, 1),
        },
        "fetch_queue": queue,
        "source_failures_open": failures,
        "database_bytes": int(_scalar(session, "SELECT pg_database_size(current_database())")),
        "store": {"files": files, "bytes": size},
    }


SAMPLE_SQL = """
SELECT c.id, c.cnr, c.case_type_text, c.reg_no, c.reg_year, c.status, c.filing_date, c.registration_date,
       c.next_hearing_date, c.last_hearing_date, c.disposal_date,
       (SELECT p.name FROM case_parties p WHERE p.case_id = c.id AND p.role = 'petitioner'
         ORDER BY p.is_current DESC, p.party_no LIMIT 1) AS petitioner,
       (SELECT p.name FROM case_parties p WHERE p.case_id = c.id AND p.role = 'respondent'
         ORDER BY p.is_current DESC, p.party_no LIMIT 1) AS respondent,
       (SELECT count(*) FROM orders o WHERE o.case_id = c.id) AS orders_held,
       (SELECT max(o.order_date) FROM orders o WHERE o.case_id = c.id) AS latest_order_date,
       (SELECT o.document_id IS NOT NULL FROM orders o WHERE o.case_id = c.id
         ORDER BY o.order_date DESC, o.order_no DESC LIMIT 1) AS latest_order_pdf_stored
FROM cases c
WHERE c.cnr IS NOT NULL AND c.last_full_refresh_at IS NOT NULL AND c.merged_into_case_id IS NULL
  AND c.status = :status
ORDER BY md5(c.cnr || :seed)
LIMIT :n
"""


def sample(session: Session, pending: int = 10, disposed: int = 10, seed: int = 0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for status, n in (("pending", pending), ("disposed", disposed)):
        if n <= 0:
            continue
        for r in session.execute(text(SAMPLE_SQL), {"status": status, "seed": str(seed), "n": n}).mappings():
            out.append(
                {
                    "cnr": r["cnr"],
                    "case": f"{r['case_type_text'] or '?'}/{r['reg_no'] or '?'}/{r['reg_year'] or '?'}",
                    "petitioner": r["petitioner"],
                    "respondent": r["respondent"],
                    "status": str(r["status"]),
                    "filing_date": r["filing_date"],
                    "registration_date": r["registration_date"],
                    "next_date": r["next_hearing_date"],
                    "last_listed_or_disposed": r["disposal_date"] or r["last_hearing_date"],
                    "orders_held": int(r["orders_held"]),
                    "latest_order_date": r["latest_order_date"],
                    "latest_order_pdf_stored": bool(r["latest_order_pdf_stored"]),
                    "court_shows": "",
                    "match": "",
                }
            )
    return out


# ------------------------------------------------------------------------------------------------ Markdown


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v).replace("|", "/").replace("\n", " ")


def report_markdown(r: dict[str, Any]) -> str:
    lines = [f"## Load counts ({r['as_of'][:16]} UTC)", ""]
    p = r["period"]
    lines.append(f"- Period held: {_cell(p['first_list_date'])} to {_cell(p['last_list_date'])}")
    sections = [
        ("Cause-list days", r["causelist_days"]),
        ("Cases", r["cases"]),
        ("Dossiers", r["dossiers"]),
        ("Orders", r["orders"]),
        ("NAPIX calls by outcome", r["napix_calls"]["by_outcome"]),
        ("Open source failures by kind", r["source_failures_open"]),
    ]
    lines.append(f"- Parties: {r['parties']}; advocates: {r['advocates']}")
    lines.append(f"- Documents with text: {r['documents_with_text']}")
    lines.append(
        f"- NAPIX calls: {r['napix_calls']['total']} in all, {r['napix_calls']['per_day_last_7_days']} a day "
        "over the last 7 days"
    )
    lines.append(
        f"- Database: {r['database_bytes']} bytes; store: {r['store']['files']} files, {r['store']['bytes']} bytes"
    )
    for title, values in sections:
        lines += ["", f"### {title}", "", "| | |", "|---|---:|"]
        lines += [f"| {k} | {v} |" for k, v in values.items()] or ["| (none) | |"]
    lines += ["", "### fetch_queue", "", "| lane | status | rows |", "|---|---|---:|"]
    lines += [f"| {q['lane']} | {q['status']} | {q['rows']} |" for q in r["fetch_queue"]]
    return "\n".join(lines) + "\n"


SAMPLE_COLUMNS = (
    ("cnr", "CNR"),
    ("case", "Case"),
    ("petitioner", "First petitioner"),
    ("respondent", "First respondent"),
    ("status", "Status"),
    ("filing_date", "Filed"),
    ("registration_date", "Registered"),
    ("next_date", "Next date"),
    ("last_listed_or_disposed", "Last listed / disposed"),
    ("orders_held", "Orders"),
    ("latest_order_date", "Latest order"),
    ("latest_order_pdf_stored", "Latest PDF stored"),
    ("court_shows", "Court shows"),
    ("match", "Match"),
)


def sample_markdown(rows: list[dict[str, Any]], seed: int) -> str:
    head = "| # | " + " | ".join(t for _, t in SAMPLE_COLUMNS) + " |"
    rule = "|---|" + "|".join("---" for _ in SAMPLE_COLUMNS) + "|"
    body = [
        f"| {i} | " + " | ".join(_cell(r[k]) for k, _ in SAMPLE_COLUMNS) + " |" for i, r in enumerate(rows, 1)
    ]
    return "\n".join([f"## Sample check (seed {seed})", "", head, rule, *body]) + "\n"
