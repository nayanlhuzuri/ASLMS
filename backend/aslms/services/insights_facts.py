"""The per-case readings of State Insights (design `state-insights`, decisions 6 to 13): `insight_case_facts`, rebuilt
by the 10-minute job `insights-refresh`, the 04:45 IST job `insights-rebuild` and `aslms insights refresh`.

- **What is stored** (decision 11): the readings only, by the rules of `services/insights_rules.py`, with no model and
  no court call: the court's category, the IA's resolved main case, the State bases `party`, `officer`, `counsel`,
  `title` and `writ` (`claimed` is evaluated live), the department phrases read, the departments they and the printed
  counsel codes name, the posts named, the printed codes, the original writ of a contempt case, the latest order date,
  the number of orders and the order whose cause title was read. Status, dates, the next hearing, ownership,
  recommendations, custody and closures are read live by `services/insights.py`.
- **When** (decision 12): a case without a row, changed since the row (`cases.updated_at`), with a new or changed
  order or a new reading of one of its orders, with a new cause-list entry, or read by an older `READER_VERSION`
  (`dirty_case_ids`, oldest first). A mapping save (counsel code, cause-title name) or a new or changed office makes
  the attribution dirty (`attribution_fingerprint` against the last run's): the department ids, the government codes
  and the `counsel` basis are derived again from the stored phrases and codes, reading no text (`rederive_departments`).
- **The cause title** is read from the span row 250 keeps (`order_sections.spans.cause_title`) of the case's latest
  order read on the template, only when the stored text is the one the reading was made from (its SHA-256); the
  current respondent party names are always read too, so the builder works without `order_sections`.
- **Never deleted** (decision 13): one row per case, updated in place; a merged case keeps its row and readers join
  live cases only. The department ids are Department-tier office ids, without FK (DB_STANDARD §2).

- **The watermark** (design `state-insights-review-advisories`, decision 1): `built_at` is the time before which every
  committed change is in the row, the build's start or 1 µs before the oldest transaction then open in this database
  (`watermark`), never more than `INSIGHTS_DIRTY_LOOKBACK_MINUTES` earlier; so a change committed by a transaction
  that was open while the build read is dirty on the next run.
- **The seed case-type lines** a case type lacks are placed first by both jobs (`insights_groups.place_seed_case_types`,
  decision 5), and a line's change makes its cases dirty. The rebuild reloads its maps when the attribution
  fingerprint moves between batches and re-derives at the end when it moved at all (decision 2).

- **The cause-title signal** (design `state-insights`, round 3, decision 36, and `cause-title-signal-review-advisories`,
  decisions 5 to 13): the matching engine reads `named_title_department_ids` and each phrase's department position
  (`title_phrase_department_pos`) from the row and no map. A build or a re-derivation that changes the departments named
  (or, while it names any, the titled order, the phrases or the positions) sets the row's durable mark
  `named_changed_at` in the same statement; the engine clears it when it scores the case, and the drain
  `rescore_marked` (run by `insights-refresh`, at the end of `rebuild` and by `aslms insights refresh` unless
  `--no-rescore`) scores every case still marked.

It writes no audit row (derived data, as the matching engine) and one `job_runs` row per run, with the counters
`checked`, `built`, `new_categories`, `rederived`, `unmapped_phrases`, `case_type_lines`, `named_changed` and
`seconds`. It never reads a note, a draft, a custody remark or a document description, and never calls NAPIX,
SourceTrace or a model."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from aslms.core.clock import today_ist
from aslms.domain.cases import Case
from aslms.domain.insights import (
    STATE_BASES,
    InsightCaseFact,
    InsightGroup,
    InsightSubjectCategory,
    OfficeTitleName,
)
from aslms.domain.ops import JobRun, JobStatus
from aslms.domain.org import Office
from aslms.domain.ownership import CounselCode
from aslms.services import access, insights_groups
from aslms.services import insights_rules as R
from aslms.services.matching import normalise_counsel_code
from aslms.services.visibility import NORMALISED_CODE_SQL

JOB_REFRESH = "insights-refresh"
JOB_REBUILD = "insights-rebuild"
JOBS = (JOB_REFRESH, JOB_REBUILD)
READ_CHUNK = 500  # the cause-title spans are read in Python batches of this size (Services)
WRIT_HEAD_CHARS = 3000  # decision 10: the first characters of the earliest order's body
COUNTERS = (
    "checked",
    "built",
    "new_categories",
    "rederived",
    "unmapped_phrases",
    "case_type_lines",
    "named_changed",
    "seconds",
)
RESCORE_BATCH = 500  # cases per transaction when the marked cases are rescored
# design cause-title-signal-review-advisories, decision 13: part of the attribution fingerprint, so the first refresh
# after a change of the attribution code (0041's positions) derives every row again
ATTRIBUTION_VERSION = "2"
# decision 10: one drain at a time, per batch transaction (PgBouncer transaction mode keeps it valid)
RESCORE_MARKED_LOCK = 0x41534C4D53_0273  # "ASLMS" + row 273


def _now() -> datetime:
    return datetime.now(UTC)


# decision 1 of state-insights-review-advisories: the oldest transaction open in this database other than this one
# (the application role sees `xact_start` of its own sessions only; other roles' show NULL and are ignored), 1 µs
# before it so the dirty test's `>` stays strict, never later than this transaction's start nor more than the
# lookback earlier
WATERMARK_SQL = """
    SELECT greatest(
        now() - make_interval(secs => :lookback_seconds),
        least(now(), (SELECT min(a.xact_start) FROM pg_stat_activity a
                      WHERE a.datname = current_database() AND a.backend_type = 'client backend'
                        AND a.pid <> pg_backend_pid() AND a.xact_start IS NOT NULL)
                     - interval '1 microsecond'))
"""


def watermark(session: Session, lookback_minutes: float | None = None) -> datetime:
    """The build's watermark (decision 1): every change committed before it is reflected in rows built now. Read
    after `pg_stat_clear_snapshot()`, so the activity view is current and not this transaction's cached copy."""
    if lookback_minutes is None:
        from aslms.core.config import get_settings

        lookback_minutes = get_settings().insights_dirty_lookback_minutes
    session.execute(text("SELECT pg_stat_clear_snapshot()"))
    return session.scalar(text(WATERMARK_SQL), {"lookback_seconds": float(lookback_minutes) * 60})


# ------------------------------------------------------------------------------------------------ the maps


@dataclass
class Maps:
    """The mappings the readings are attributed through, loaded once per run."""

    generic: frozenset[str] = frozenset()
    code_departments: dict[str, frozenset[uuid.UUID]] = field(default_factory=dict)
    explicit: dict[str, uuid.UUID] = field(default_factory=dict)  # phrase -> Department-tier office id
    cores: dict[str, uuid.UUID] = field(default_factory=dict)  # name core -> Department-tier office id

    @property
    def mapped(self) -> frozenset[str]:
        return frozenset(self.code_departments)

    def phrase_department(self, phrase: str) -> uuid.UUID | None:
        """Decision 9: an explicit active mapping of the phrase, else the automatic match on a department's name core."""
        dept = self.explicit.get(phrase)
        if dept is None:
            dept = self.cores.get(R.office_name_core(phrase))
        return dept

    def phrase_departments(self, phrases: list[str]) -> list[uuid.UUID]:
        """Each department the phrases name once, in the order of the phrases."""
        return self.phrase_positions(phrases)[0]

    def phrase_positions(self, phrases: list[str]) -> tuple[list[uuid.UUID], list[int]]:
        """Design cause-title-signal-review-advisories, decision 6: the departments named (as `phrase_departments`)
        and, parallel to `phrases`, the 1-based position among them of the department each phrase names, 0 for
        none."""
        ids: list[uuid.UUID] = []
        positions: list[int] = []
        for p in phrases:
            dept = self.phrase_department(p)
            if dept is None:
                positions.append(0)
                continue
            if dept not in ids:
                ids.append(dept)
            positions.append(ids.index(dept) + 1)
        return ids, positions

    def is_unmapped(self, phrase: str) -> bool:
        return phrase not in self.explicit and R.office_name_core(phrase) not in self.cores

    def code_departments_of(self, codes: list[str]) -> list[uuid.UUID]:
        out: list[uuid.UUID] = []
        for c in codes:
            for d in sorted(self.code_departments.get(c, ()), key=str):
                if d not in out:
                    out.append(d)
        return out

    def government_codes(self, codes: list[str]) -> list[str]:
        return [c for c in codes if R.is_government_code(c, self.mapped, self.generic)]


def _department_ids(session: Session) -> dict[str, Office]:
    """Department-tier offices by code (active or not: an id once attributed stays a real office)."""
    rows = session.scalars(
        select(Office).where(
            Office.parent_id.is_not(None), Office.kind.in_(list(access.DEPARTMENT_TIER_KINDS))
        )
    ).all()
    return {o.code: o for o in rows if access.is_department(o)}


def _department_id_of(office: Office | None, departments: dict[str, Office]) -> uuid.UUID | None:
    """The Department-tier ancestor of an office (the second segment of its path), as scoring attributes."""
    if office is None:
        return None
    parts = office.path.split("/")
    if len(parts) < 2:
        return None
    dept = departments.get(parts[1])
    return dept.id if dept is not None else None


def load_maps(session: Session) -> Maps:
    departments = _department_ids(session)
    offices = {o.id: o for o in session.scalars(select(Office)).all()}
    generic: set[str] = set()
    code_depts: dict[str, set[uuid.UUID]] = {}
    for code, office_id, is_generic in session.execute(
        select(CounselCode.code, CounselCode.office_id, CounselCode.is_generic_state).where(
            CounselCode.is_active.is_(True)
        )
    ).all():
        norm = normalise_counsel_code(code)
        if not norm:
            continue
        if is_generic:
            generic.add(norm)
            continue
        dept = _department_id_of(offices.get(office_id), departments)
        if dept is not None:
            code_depts.setdefault(norm, set()).add(dept)
    explicit: dict[str, uuid.UUID] = {}
    for phrase, office_id in session.execute(
        select(OfficeTitleName.phrase, OfficeTitleName.office_id).where(OfficeTitleName.is_active.is_(True))
    ).all():
        dept = _department_id_of(offices.get(office_id), departments)
        if dept is not None:
            explicit[phrase] = dept
    cores: dict[str, uuid.UUID] = {}
    for d in sorted(departments.values(), key=lambda o: (not o.is_active, o.code)):
        core = R.office_name_core(d.name)
        if core and len(core) >= R.PHRASE_MIN:
            cores.setdefault(core, d.id)
    return Maps(
        generic=frozenset(generic),
        code_departments={k: frozenset(v) for k, v in code_depts.items()},
        explicit=explicit,
        cores=cores,
    )


ATTRIBUTION_SQL = {
    # every column the attribution reads, so a change in the same transaction as the build is seen too
    "counsel_codes": "code || '|' || office_id::text || '|' || is_active::text || '|' || is_generic_state::text",
    "office_title_names": "phrase || '|' || office_id::text || '|' || is_active::text",
    "offices": "code || '|' || name || '|' || path || '|' || kind || '|' || is_active::text",
}


def attribution_fingerprint(session: Session) -> str:
    """One md5 over the attribution code's version and what the attribution reads (counsel codes, cause-title names,
    offices): each table's row count and an md5 of every row's content in id order, so any mapping or office change,
    active or not, changes it, and so does a new `ATTRIBUTION_VERSION`."""
    parts = [
        f"(SELECT count(*)::text || ':' || coalesce(md5(string_agg({cols}, ',' ORDER BY id)), '') FROM {table})"
        for table, cols in ATTRIBUTION_SQL.items()
    ]
    return str(
        session.scalar(
            text(f"SELECT md5(concat_ws('|', CAST(:version AS text), {', '.join(parts)}))"),
            {"version": ATTRIBUTION_VERSION},
        )
    )


def _last_fingerprint(session: Session) -> str | None:
    counters = session.scalar(
        select(JobRun.counters)
        .where(JobRun.job.in_(JOBS), JobRun.status == JobStatus.SUCCEEDED)
        .order_by(JobRun.started_at.desc(), JobRun.id.desc())
        .limit(1)
    )
    return (counters or {}).get("attribution_fingerprint")


def attribution_dirty(session: Session) -> bool:
    return attribution_fingerprint(session) != _last_fingerprint(session)


# ------------------------------------------------------------------------------------------------ dirty cases

DIRTY_SQL = """
    FROM cases c
    LEFT JOIN insight_case_facts f ON f.case_id = c.id
    WHERE c.merged_into_case_id IS NULL AND (
        f.case_id IS NULL
        OR f.reader_version <> :version
        OR c.updated_at > f.built_at
        OR EXISTS (SELECT 1 FROM orders o WHERE o.case_id = c.id AND o.updated_at > f.built_at)
        OR EXISTS (SELECT 1 FROM orders o JOIN order_sections os ON os.order_id = o.id
                   WHERE o.case_id = c.id AND os.created_at > f.built_at)
        OR EXISTS (SELECT 1 FROM causelist_entries e WHERE e.case_id = c.id AND e.created_at > f.built_at)
        OR EXISTS (SELECT 1 FROM insight_case_type_groups ctg
                   WHERE ctg.case_type_id = c.case_type_id AND ctg.updated_at > f.built_at)
    )
"""


def dirty_case_ids(session: Session, limit: int) -> list[uuid.UUID]:
    """Decision 12: the live cases whose readings are missing or stale, oldest first (no row first, then by
    `built_at`), at most `limit`."""
    return list(
        session.scalars(
            text(f"SELECT c.id {DIRTY_SQL} ORDER BY f.built_at ASC NULLS FIRST, c.id LIMIT :limit"),
            {"version": R.READER_VERSION, "limit": int(limit)},
        ).all()
    )


def dirty_count(session: Session) -> tuple[int, datetime | None]:
    """(cases waiting, the oldest waiting since): no row counts from the case's creation, a stale row from its build."""
    n, oldest = session.execute(
        text(f"SELECT count(*), min(coalesce(f.built_at, c.created_at)) {DIRTY_SQL}"),
        {"version": R.READER_VERSION},
    ).one()
    return int(n or 0), oldest


# ------------------------------------------------------------------------------------------------ reading


@dataclass
class CaseInput:
    id: uuid.UUID
    court_id: uuid.UUID
    category: str | None
    category_code: int | None
    contempt: bool
    petitioners: list[str] = field(default_factory=list)
    respondents: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    orders_count: int = 0
    latest_order_on: Any = None
    main_case_id: uuid.UUID | None = None
    title_order_id: uuid.UUID | None = None
    title_text: str | None = None
    writ_sources: list[str] = field(default_factory=list)


CASES_SQL = """
    SELECT c.id, c.court_id, c.category, c.category_code,
           coalesce(g.code = 'contempt', false) AS contempt
    FROM cases c
    LEFT JOIN insight_case_type_groups ctg ON ctg.case_type_id = c.case_type_id
    LEFT JOIN insight_groups g ON g.id = ctg.group_id AND g.is_active
    WHERE c.id = ANY(:ids)
"""
PARTIES_SQL = """
    SELECT case_id, role::text, name FROM case_parties
    WHERE case_id = ANY(:ids) AND is_current ORDER BY case_id, role, party_no
"""
CODES_SQL = f"""
    SELECT case_id, array_agg(DISTINCT code ORDER BY code) FROM (
        SELECT e.case_id, {NORMALISED_CODE_SQL.format(col="x.code")} AS code
        FROM causelist_entries e JOIN causelists cl ON cl.id = e.causelist_id
        CROSS JOIN LATERAL unnest(e.counsel_codes) AS x(code)
        WHERE e.case_id = ANY(:ids) AND cl.superseded_at IS NULL
        UNION
        SELECT a.case_id, {NORMALISED_CODE_SQL.format(col="a.counsel_code")}
        FROM case_advocates a WHERE a.case_id = ANY(:ids) AND a.is_current AND a.counsel_code IS NOT NULL
    ) t WHERE code <> '' GROUP BY case_id
"""
ORDERS_SQL = """
    SELECT case_id, count(*), max(order_date) FROM orders WHERE case_id = ANY(:ids) GROUP BY case_id
"""
MAIN_SQL = """
    SELECT DISTINCT ON (l.from_case_id) l.from_case_id, coalesce(t.merged_into_case_id, t.id)
    FROM case_links l JOIN cases t ON t.id = l.to_case_id
    WHERE l.from_case_id = ANY(:ids) AND l.kind = 'main_matter' AND l.from_case_id <> t.id
    ORDER BY l.from_case_id, l.created_at, l.id
"""
# the cause-title span of the latest order read on the template, cut only from the very text the reading was made from
TITLE_SQL = """
    SELECT DISTINCT ON (o.case_id) o.case_id, o.id,
           CASE WHEN encode(sha256(convert_to(dt.full_text, 'UTF8')), 'hex') = os.text_sha256
                THEN substr(dt.full_text, (os.spans->'cause_title'->>0)::int + 1,
                            (os.spans->'cause_title'->>1)::int - (os.spans->'cause_title'->>0)::int)
           END
    FROM orders o
    JOIN order_sections os ON os.order_id = o.id AND os.replaced_at IS NULL
    JOIN document_text dt ON dt.document_id = os.document_id
    WHERE o.case_id = ANY(:ids) AND os.layout = 'template' AND os.spans ? 'cause_title'
    ORDER BY o.case_id, o.order_date DESC, o.id DESC
"""
# decision 10, the original writ of a contempt case: source 1, the `Linked Case :` entries of its readings
LINKED_SQL = """
    SELECT o.case_id, lc->>'case_no'
    FROM orders o
    JOIN order_sections os ON os.order_id = o.id AND os.replaced_at IS NULL
    CROSS JOIN LATERAL jsonb_array_elements(os.linked_cases) AS lc
    WHERE o.case_id = ANY(:ids) AND lc->>'case_no' IS NOT NULL
    ORDER BY o.case_id, o.order_date DESC, o.id DESC
"""
# source 2, the first characters of the body of the case's earliest order with text
EARLIEST_SQL = f"""
    SELECT DISTINCT ON (o.case_id) o.case_id,
           coalesce(left(os.body_text, {WRIT_HEAD_CHARS}), left(dt.full_text, {WRIT_HEAD_CHARS}))
    FROM orders o
    JOIN documents d ON d.id = o.document_id
    JOIN document_text dt ON dt.document_id = d.id
    LEFT JOIN order_sections os ON os.order_id = o.id AND os.replaced_at IS NULL
    WHERE o.case_id = ANY(:ids) AND dt.full_text IS NOT NULL AND dt.full_text <> ''
    ORDER BY o.case_id, o.order_date, o.id
"""


def _order_texts(session: Session, inputs: dict[uuid.UUID, CaseInput]) -> None:
    """The only reader of order text in Insights (decision 20's scan allows it here): the cause-title span of the
    latest order read on the template, and, for contempt cases, the `Linked Case :` entries and the head of the
    earliest order's body. Read in chunks of `READ_CHUNK` cases."""
    ids = list(inputs)
    for i in range(0, len(ids), READ_CHUNK):
        chunk = ids[i : i + READ_CHUNK]
        for case_id, order_id, title in session.execute(text(TITLE_SQL), {"ids": chunk}).all():
            if title:
                inputs[case_id].title_order_id = order_id
                inputs[case_id].title_text = title
        contempt = [c for c in chunk if inputs[c].contempt]
        if not contempt:
            continue
        for case_id, case_no in session.execute(text(LINKED_SQL), {"ids": contempt}).all():
            inputs[case_id].writ_sources.append(case_no)
        for case_id, head in session.execute(text(EARLIEST_SQL), {"ids": contempt}).all():
            if head:
                inputs[case_id].writ_sources.append(head)


def gather(session: Session, case_ids: list[uuid.UUID]) -> dict[uuid.UUID, CaseInput]:
    """Everything the rules read, for a batch of cases, in set-based statements."""
    inputs: dict[uuid.UUID, CaseInput] = {}
    for cid, court_id, category, category_code, contempt in session.execute(
        text(CASES_SQL), {"ids": case_ids}
    ).all():
        inputs[cid] = CaseInput(cid, court_id, category, category_code, bool(contempt))
    if not inputs:
        return inputs
    ids = list(inputs)
    for cid, role, name in session.execute(text(PARTIES_SQL), {"ids": ids}).all():
        (inputs[cid].respondents if role == "respondent" else inputs[cid].petitioners).append(name or "")
    for cid, codes in session.execute(text(CODES_SQL), {"ids": ids}).all():
        inputs[cid].codes = [c for c in codes if c][:200]
    for cid, n, latest in session.execute(text(ORDERS_SQL), {"ids": ids}).all():
        inputs[cid].orders_count, inputs[cid].latest_order_on = int(n), latest
    for cid, main in session.execute(text(MAIN_SQL), {"ids": ids}).all():
        inputs[cid].main_case_id = main
    _order_texts(session, inputs)
    return inputs


def _clip(values: list[str], n: int) -> list[str]:
    return [v[:n] for v in values]


def read_case(inp: CaseInput, maps: Maps, *, today) -> dict[str, Any]:
    """The rules over one case's inputs: the row's values, the `writ` basis and the writ's case still to come."""
    respondents_text = " ; ".join(inp.respondents)
    title_respondents = R.respondent_side(inp.title_text) if inp.title_text else ""
    phrases: list[str] = []
    for source in (title_respondents, *inp.respondents):
        for p in R.department_phrases(source):
            if p not in phrases:
                phrases.append(p)
    bases: list[str] = []
    if any(R.names_state(n) for n in (*inp.petitioners, *inp.respondents)):
        bases.append("party")
    if any(R.has_service_tag(n) for n in inp.respondents):
        bases.append("officer")
    gov = maps.government_codes(inp.codes)
    if gov:
        bases.append("counsel")
    if inp.title_text and R.names_state(inp.title_text):
        bases.append("title")
    post_codes: list[str] = []
    for source in (title_respondents, respondents_text):
        for p in R.posts(source):
            if p not in post_codes:
                post_codes.append(p)
    post_codes = [c for c in R.POST_CODES if c in post_codes]
    # decision 6 of cause-title-signal-review-advisories: the departments and positions from the stored (clipped)
    # phrases, as the re-derivation reads them
    stored = _clip(phrases, 200)[:100]
    named_ids, positions = maps.phrase_positions(stored)
    writ = None
    if inp.contempt:
        for src in inp.writ_sources:
            writ = R.writ_reference(src, today=today)
            if writ:
                break
    parsed = R.parse_category(inp.category)
    category = parsed[0] if parsed else None
    return {
        "case_id": inp.id,
        "category_code": category,
        "subject_category_code": category,
        "main_case_id": inp.main_case_id,
        "state_basis": bases,
        "title_phrases": stored,
        "title_phrase_department_pos": positions,
        "named_title_department_ids": named_ids,
        "named_counsel_department_ids": maps.code_departments_of(inp.codes),
        "posts": post_codes,
        "counsel_codes": _clip(inp.codes, 120),
        "government_codes": _clip(gov, 120),
        "original_writ_text": writ,
        "original_writ_case_id": None,
        "latest_order_on": inp.latest_order_on,
        "orders_count": inp.orders_count,
        "title_order_id": inp.title_order_id,
        "reader_version": R.READER_VERSION,
        "_category_label": parsed[1] if parsed else None,
        "_court_id": inp.court_id,
    }


WRIT_CASE_SQL = """
    SELECT c.id, c.category FROM cases c
    JOIN case_types ct ON ct.id = c.case_type_id
    WHERE c.court_id = :court AND c.merged_into_case_id IS NULL AND c.reg_no = :no AND c.reg_year = :year
      AND (upper(regexp_replace(coalesce(ct.short_name, ''), '[[:space:].]', '', 'g')) = :type
           OR EXISTS (SELECT 1 FROM unnest(ct.aliases) a
                      WHERE upper(regexp_replace(a, '[[:space:].]', '', 'g')) = :type))
    ORDER BY c.id LIMIT 1
"""


def _resolve_writs(session: Session, rows: list[dict[str, Any]]) -> None:
    """Decision 10: `original_writ_case_id` only when ASLMS holds that case (same court, the case type by its short
    name or aliases, `reg_no` and `reg_year`); the contempt case then takes the writ's subject category. Nothing is
    invented: an unresolved writ stays text. Never written to `case_links`."""
    for row in rows:
        writ = row["original_writ_text"]
        if not writ:
            continue
        parts = R.writ_parts(writ)
        if parts is None:
            continue
        type_compact, no, year = parts
        found = session.execute(
            text(WRIT_CASE_SQL), {"court": row["_court_id"], "no": no, "year": year, "type": type_compact}
        ).first()
        if found is None or found[0] == row["case_id"]:
            continue
        row["original_writ_case_id"] = found[0]
        parsed = R.parse_category(found[1])
        if parsed:
            row["subject_category_code"] = parsed[0]


def _discover(session: Session, rows: list[dict[str, Any]], now: datetime) -> int:
    """A category a case carries for the first time is inserted with no group (Not Grouped, decision 15)."""
    seen: dict[tuple[uuid.UUID, int], str] = {}
    for row in rows:
        if row["category_code"] is not None and row["_category_label"]:
            seen.setdefault((row["_court_id"], row["category_code"]), row["_category_label"])
    if not seen:
        return 0
    held = {
        (c, k)
        for c, k in session.execute(
            select(InsightSubjectCategory.court_id, InsightSubjectCategory.category_code).where(
                InsightSubjectCategory.category_code.in_({k for _, k in seen})
            )
        ).all()
    }
    new = [
        {"court_id": c, "category_code": k, "label": label, "first_seen_at": now, "last_seen_at": now}
        for (c, k), label in seen.items()
        if (c, k) not in held
    ]
    if new:
        session.execute(
            pg_insert(InsightSubjectCategory)
            .values(new)
            .on_conflict_do_nothing(index_elements=["court_id", "category_code"])
        )
    return len(new)


WRIT_BASIS_SQL = """
    UPDATE insight_case_facts f
    SET state_basis = CASE
            WHEN w.case_id IS NOT NULL AND (
                cardinality(array_remove(w.state_basis, 'writ'::varchar)) > 0
                OR cardinality(w.named_title_department_ids) > 0
                OR EXISTS (SELECT 1 FROM case_ownership ow WHERE ow.case_id = w.case_id
                           AND ow.status = 'active' AND ow.role = 'primary'))
            THEN array_append(array_remove(f.state_basis, 'writ'::varchar), 'writ'::varchar)
            ELSE array_remove(f.state_basis, 'writ'::varchar)
        END
    FROM insight_case_facts f2
    LEFT JOIN insight_case_facts w ON w.case_id = f2.original_writ_case_id
    WHERE f.case_id = f2.case_id AND f.case_id = ANY(:ids)
      AND (f.original_writ_case_id IS NOT NULL OR 'writ' = ANY(f.state_basis))
"""


def build(
    session: Session, case_ids: list[uuid.UUID], *, maps: Maps | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Rebuilds the fact rows of `case_ids` (live or merged alike; readers join live cases): the set-based reads, the
    rules in Python, the writ resolution, `INSERT … ON CONFLICT (case_id) DO UPDATE`, then the `writ` basis as a
    second pass (the writ's own row is read after its own build). `built_at` is the watermark, taken before any case
    data is read (decision 1 of state-insights-review-advisories); a given `now` (tests) stands for all three times."""
    if not case_ids:
        return {"built": 0, "new_categories": 0, "named_changed": 0}
    if now is None:
        built_at = watermark(session)
        now = session.scalar(select(func.now()))
    else:
        built_at = now
    maps = maps or load_maps(session)
    today = today_ist(now)
    inputs = gather(session, case_ids)
    rows = [read_case(inp, maps, today=today) for inp in inputs.values()]
    _resolve_writs(session, rows)
    new_categories = _discover(session, rows, now)
    # written in key order, so two writers never take the same rows in opposite orders
    rows.sort(key=lambda r: r["case_id"])
    changed = set(_named_changed(session, rows))
    # decision 8 of cause-title-signal-review-advisories: the durable rescore mark, in the same statement as the row;
    # a row not listed keeps a pending mark
    values = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        | {
            "built_at": built_at,
            "named_changed_at": func.clock_timestamp() if r["case_id"] in changed else None,
        }
        for r in rows
    ]
    table = InsightCaseFact.__table__
    for i in range(0, len(values), 1000):
        part = values[i : i + 1000]
        stmt = pg_insert(InsightCaseFact).values(part)
        update = {c: stmt.excluded[c] for c in part[0] if c not in ("case_id", "named_changed_at")}
        update["named_changed_at"] = func.coalesce(stmt.excluded.named_changed_at, table.c.named_changed_at)
        session.execute(stmt.on_conflict_do_update(index_elements=["case_id"], set_=update))
    session.execute(text(WRIT_BASIS_SQL), {"ids": [r["case_id"] for r in rows]})
    session.flush()
    return {"built": len(rows), "new_categories": new_categories, "named_changed": len(changed)}


NAMED_OLD_SQL = """
    SELECT case_id, named_title_department_ids, title_order_id, title_phrases, title_phrase_department_pos
    FROM insight_case_facts WHERE case_id = ANY(:ids)
"""


def _named_changed(session: Session, rows: list[dict[str, Any]]) -> list[uuid.UUID]:
    """The cases of `rows` whose cause-title signal may change (design state-insights, decision 36, and
    cause-title-signal-review-advisories, decision 7): the departments named differ from the stored row's (no row reads
    as none), or, while it names any, the titled order, the phrases or their department positions differ (the phrase
    shown and the reason sentence follow them)."""
    if not rows:
        return []
    old = {
        r.case_id: r
        for r in session.execute(text(NAMED_OLD_SQL), {"ids": [r["case_id"] for r in rows]}).all()
    }
    out: list[uuid.UUID] = []
    for row in rows:
        new_ids = list(row["named_title_department_ids"])
        prev = old.get(row["case_id"])
        if prev is None:
            if new_ids:
                out.append(row["case_id"])
            continue
        if new_ids != list(prev.named_title_department_ids or []) or (
            new_ids
            and (
                row["title_order_id"] != prev.title_order_id
                or list(row["title_phrases"]) != list(prev.title_phrases or [])
                or list(row["title_phrase_department_pos"]) != list(prev.title_phrase_department_pos or [])
            )
        ):
            out.append(row["case_id"])
    return out


def rescore_marked(
    session_factory: sessionmaker[Session],
    *,
    batch: int = 0,
    stop_at: datetime | None = None,
):
    """Design cause-title-signal-review-advisories, decision 10, the drain: the matching engine run on every case whose
    fact row carries a rescore mark set at or before the drain's start (`stop_at`, default the database clock when the
    drain starts; a newer mark waits for the next drain), `RESCORE_BATCH` cases per transaction in case-id order. Each
    batch transaction takes `RESCORE_MARKED_LOCK` with `pg_try_advisory_xact_lock` and stops when another drain holds
    it. The engine clears the mark of each case it scores; the marks of the cases that failed (recorded by the engine in
    `source_failures`, kind `scoring`) are cleared here with the same equality test, so a broken case cannot loop. Never
    raises for one case; returns the engine's `ScoreReport`."""
    from aslms.domain.ownership import RecommendationOrigin
    from aslms.services import matching

    size = batch or RESCORE_BATCH
    total = matching.ScoreReport()
    if stop_at is None:
        with session_factory() as s:
            stop_at = s.scalar(select(func.clock_timestamp()))
            s.rollback()
    last: uuid.UUID | None = None
    while True:
        with session_factory() as s:
            if not s.scalar(select(func.pg_try_advisory_xact_lock(RESCORE_MARKED_LOCK))):
                s.rollback()
                break
            stmt = (
                select(InsightCaseFact.case_id, InsightCaseFact.named_changed_at)
                .where(
                    InsightCaseFact.named_changed_at.is_not(None),
                    InsightCaseFact.named_changed_at <= stop_at,
                )
                .order_by(InsightCaseFact.case_id)
                .limit(size)
            )
            if last is not None:
                stmt = stmt.where(InsightCaseFact.case_id > last)
            rows = s.execute(stmt).all()
            if not rows:
                s.rollback()
                break
            marks = {r.case_id: r.named_changed_at for r in rows}
            report = matching.score_cases(s, list(marks), origin=RecommendationOrigin.RESCORE)
            for case_id in report.failed_case_ids:
                s.execute(text(matching.CLEAR_MARK_SQL), {"id": case_id, "read": marks.get(case_id)})
            s.commit()
        total.add(report)
        last = rows[-1].case_id
    return total


def marked_count(session: Session) -> int:
    """The live cases whose fact row carries a rescore mark (decision 12, `named_rescore_waiting`)."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(InsightCaseFact)
            .join(Case, Case.id == InsightCaseFact.case_id)
            .where(InsightCaseFact.named_changed_at.is_not(None), Case.merged_into_case_id.is_(None))
        )
        or 0
    )


def rederive_departments(
    session: Session, maps: Maps | None = None, named_changed: dict[str, int] | None = None
) -> int:
    """Decision 12: after a mapping or office change, the department ids, each phrase's department position, the
    government codes and the `counsel` basis of every row are derived again from the stored phrases and codes; no text
    is read. Only changed rows are written (Deviation 5: in Python over the stored arrays rather than one SQL statement,
    so the rules are written once). A row whose departments named changed, or, while it names any, whose positions
    changed, is marked for rescoring in the same UPDATE (design cause-title-signal-review-advisories, decisions 7 and
    8); `named_changed["marked"]` counts the rows marked."""
    maps = maps or load_maps(session)
    changed = 0
    batch: list[dict[str, Any]] = []
    rows = session.execute(
        select(
            InsightCaseFact.case_id,
            InsightCaseFact.title_phrases,
            InsightCaseFact.counsel_codes,
            InsightCaseFact.state_basis,
            InsightCaseFact.named_title_department_ids,
            InsightCaseFact.named_counsel_department_ids,
            InsightCaseFact.government_codes,
            InsightCaseFact.title_phrase_department_pos,
        )
        # Case-id order, the order engine passes clear marks in, so the two never wait on each other's rows
        # in opposite orders (row 273 review advisory: lock-order inversion).
        .order_by(InsightCaseFact.case_id)
    ).yield_per(5000)
    for case_id, phrases, codes, basis, t_ids, c_ids, gov_old, pos_old in rows:
        t_new, pos_new = maps.phrase_positions(list(phrases or []))
        c_new = maps.code_departments_of(list(codes or []))
        gov = maps.government_codes(list(codes or []))
        kept = set(basis or []) - {"counsel"}
        b = [x for x in STATE_BASES if x in kept or (x == "counsel" and gov)]
        old_t, old_pos = list(t_ids or []), list(pos_old or [])
        same = (t_new, c_new, gov, b, pos_new) == (
            old_t,
            list(c_ids or []),
            list(gov_old or []),
            list(basis or []),
            old_pos,
        )
        if same:
            continue
        mark = t_new != old_t or (bool(t_new) and pos_new != old_pos)
        if mark and named_changed is not None:
            named_changed["marked"] = named_changed.get("marked", 0) + 1
        batch.append({"cid": case_id, "t": t_new, "c": c_new, "g": gov, "b": b, "p": pos_new, "m": mark})
        if len(batch) >= 1000:
            changed += _write_rederived(session, batch)
            batch = []
    if batch:
        changed += _write_rederived(session, batch)
    return changed


REDERIVE_SQL = """
    UPDATE insight_case_facts SET named_title_department_ids = :t, named_counsel_department_ids = :c,
        government_codes = :g, state_basis = :b, title_phrase_department_pos = CAST(:p AS smallint[]),
        named_changed_at = CASE WHEN :m THEN clock_timestamp() ELSE named_changed_at END
    WHERE case_id = :cid
"""


def _write_rederived(session: Session, batch: list[dict[str, Any]]) -> int:
    for item in batch:
        session.execute(text(REDERIVE_SQL), item)
    return len(batch)


def unmapped_phrases(session: Session, maps: Maps | None = None) -> list[tuple[str, int]]:
    """The phrases of live cases' readings that no active mapping and no automatic match names, with their number of
    cases, most first (the unmapped list of decision 9 and the data-health count)."""
    maps = maps or load_maps(session)
    rows = session.execute(
        text(
            "SELECT p, count(DISTINCT f.case_id) FROM insight_case_facts f JOIN cases c ON c.id = f.case_id "
            "CROSS JOIN LATERAL unnest(f.title_phrases) AS p WHERE c.merged_into_case_id IS NULL GROUP BY p"
        )
    ).all()
    out = [(p, int(n)) for p, n in rows if maps.is_unmapped(p)]
    out.sort(key=lambda t: (-t[1], t[0]))
    return out


def discover_categories(session: Session, now: datetime | None = None) -> int:
    """Every live case's category: a new one inserted with no group; the label and `last_seen_at` of a held one follow
    the court. Returns the number of new categories."""
    now = now or _now()
    seen: dict[tuple[uuid.UUID, int], str] = {}
    for court_id, category in session.execute(
        select(Case.court_id, Case.category)
        .where(Case.merged_into_case_id.is_(None), Case.category.is_not(None))
        .distinct()
    ).all():
        parsed = R.parse_category(category)
        if parsed:
            seen.setdefault((court_id, parsed[0]), parsed[1])
    held = {(r.court_id, r.category_code): r for r in session.scalars(select(InsightSubjectCategory)).all()}
    new = 0
    for key, label in seen.items():
        row = held.get(key)
        if row is None:
            session.add(
                InsightSubjectCategory(
                    court_id=key[0], category_code=key[1], label=label, first_seen_at=now, last_seen_at=now
                )
            )
            new += 1
        else:
            if row.label != label:
                row.label = label
            row.last_seen_at = now
    session.flush()
    return new


# ------------------------------------------------------------------------------------------------ the runs


@dataclass
class RunReport:
    checked: int = 0
    built: int = 0
    new_categories: int = 0
    rederived: int = 0
    unmapped_phrases: int = 0
    case_type_lines: int = 0
    seconds: float = 0.0
    named_changed: int = 0
    attribution_fingerprint: str | None = None
    dry_run: bool = False
    # the cases the drain scored after the run (design cause-title-signal-review-advisories, decision 12); not stored
    rescored: int | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {k: getattr(self, k) for k in COUNTERS}
        out["seconds"] = round(self.seconds, 2)
        if self.attribution_fingerprint:
            out["attribution_fingerprint"] = self.attribution_fingerprint
        if self.dry_run:
            out["dry_run"] = True
        if self.rescored is not None:
            out["rescored"] = self.rescored
        return out


def _job(session: Session, job: str) -> JobRun:
    run = JobRun(job=job, run_date=today_ist())
    session.add(run)
    session.flush()
    return run


def refresh(
    session: Session, *, batch: int = 5000, dry_run: bool = False, now: datetime | None = None
) -> RunReport:
    """The 10-minute job: the seed case-type lines a case type lacks placed first (decision 5 of
    state-insights-review-advisories), at most `batch` dirty cases rebuilt, then the attribution derived again when a
    mapping or an office changed. One transaction (the caller commits); one `job_runs` row `insights-refresh`.
    `dry_run` counts what would be placed and built and writes nothing."""
    started = time.monotonic()
    report = RunReport(dry_run=dry_run)
    if dry_run:
        report.case_type_lines = insights_groups.count_seed_case_types_missing(session)
        report.checked, _ = dirty_count(session)
        report.rederived = 1 if attribution_dirty(session) else 0
        report.seconds = time.monotonic() - started
        return report
    run = _job(session, JOB_REFRESH)
    try:
        report.case_type_lines = insights_groups.place_seed_case_types(session)
        fingerprint = attribution_fingerprint(session)
        maps = load_maps(session)
        ids = dirty_case_ids(session, batch)
        report.checked = len(ids)
        out = build(session, ids, maps=maps, now=now)
        report.built, report.new_categories = out["built"], out["new_categories"]
        marked = {"marked": int(out["named_changed"])}
        if fingerprint != _last_fingerprint(session):
            report.rederived = rederive_departments(session, maps, named_changed=marked)
        report.named_changed = marked["marked"]
        report.unmapped_phrases = len(unmapped_phrases(session, maps))
        report.attribution_fingerprint = fingerprint
        report.seconds = time.monotonic() - started
        run.counters = report.as_dict()
        run.status = JobStatus.SUCCEEDED
    except Exception as exc:
        run.status, run.error = JobStatus.FAILED, f"{exc.__class__.__name__}: {exc}"[:2000]
        raise
    finally:
        run.finished_at = _now()
        session.flush()
    return report


# the transaction-scoped advisory lock of one refresh at a time (PgBouncer transaction mode keeps it valid)
REFRESH_LOCK = 0x41534C4D53_0258  # "ASLMS" + row 258


def refresh_if_free(session: Session, *, batch: int = 5000) -> RunReport | None:
    """`refresh` when no other refresh holds the lock (`pg_try_advisory_xact_lock`); None otherwise. The caller
    commits, which releases the lock."""
    if not session.scalar(select(func.pg_try_advisory_xact_lock(REFRESH_LOCK))):
        return None
    return refresh(session, batch=batch)


def rebuild(
    session_factory: sessionmaker[Session],
    *,
    batch: int = 5000,
    job: str = JOB_REBUILD,
    echo: Callable[[str], Any] | None = None,
    rescore: bool = True,
) -> RunReport:
    """`insights-rebuild` (04:45 IST) and `aslms insights refresh --all`: the seed case-type lines a case type lacks
    placed first, every live case rebuilt in batches of `batch`, each its own transaction under `REFRESH_LOCK`, then
    the categories discovered and one `job_runs` row with the counters. Then, unless `rescore` is False, the marked
    cases are scored by the drain (`rescore_marked`, design cause-title-signal-review-advisories, decision 12); a failed
    rebuild leaves the marks of its committed batches to the next drain.

    Decision 2 of state-insights-review-advisories: each batch reads the attribution fingerprint under the lock and
    reloads the maps when it moved (the fingerprint always before the maps), so no batch is written with maps older
    than a fingerprint some refresh has recorded; the end step, under the lock, re-derives every row with maps loaded
    after the final fingerprint when any batch used maps of another fingerprint, so the fingerprint recorded is true of
    every row written."""
    started = time.monotonic()
    report = RunReport()
    with session_factory() as s:
        run_id = _job(s, job).id
        s.commit()
    status, error = JobStatus.FAILED, None
    try:
        with session_factory() as s:
            s.execute(select(func.pg_advisory_xact_lock(REFRESH_LOCK)))
            report.case_type_lines = insights_groups.place_seed_case_types(s)
            s.commit()
        maps: Maps | None = None
        maps_fingerprint: str | None = None
        used: set[str] = set()
        marked = {"marked": 0}
        last: uuid.UUID | None = None
        while True:
            with session_factory() as s:
                # one writer at a time: a 10-minute refresh skips while a rebuild batch holds the lock
                s.execute(select(func.pg_advisory_xact_lock(REFRESH_LOCK)))
                stmt = (
                    select(Case.id).where(Case.merged_into_case_id.is_(None)).order_by(Case.id).limit(batch)
                )
                if last is not None:
                    stmt = stmt.where(Case.id > last)
                ids = list(s.scalars(stmt).all())
                if not ids:
                    break
                current = attribution_fingerprint(s)
                if maps is None or current != maps_fingerprint:
                    maps, maps_fingerprint = load_maps(s), current
                used.add(current)
                out = build(s, ids, maps=maps)
                s.commit()
            marked["marked"] += int(out["named_changed"])
            report.checked += len(ids)
            report.built += out["built"]
            report.new_categories += out["new_categories"]
            last = ids[-1]
            if echo is not None:
                echo(f"built {report.built}")
        with session_factory() as s:
            s.execute(select(func.pg_advisory_xact_lock(REFRESH_LOCK)))
            final = attribution_fingerprint(s)
            end_maps = maps if final == maps_fingerprint and maps is not None else load_maps(s)
            if used - {final}:
                report.rederived += rederive_departments(s, end_maps, named_changed=marked)
            report.new_categories += discover_categories(s)
            report.unmapped_phrases = len(unmapped_phrases(s, end_maps))
            s.commit()
        report.attribution_fingerprint = final
        report.named_changed = marked["marked"]
        status = JobStatus.SUCCEEDED
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"[:2000]
        raise
    finally:
        report.seconds = time.monotonic() - started
        with session_factory() as s:
            run = s.get(JobRun, run_id)
            run.status, run.error, run.finished_at = status, error, _now()
            run.counters = report.as_dict()
            s.commit()
    if rescore:
        report.rescored = rescore_marked(session_factory).cases
    return report


def _last_run(session: Session, job: str) -> dict[str, Any] | None:
    run = session.scalar(select(JobRun).where(JobRun.job == job).order_by(JobRun.started_at.desc()).limit(1))
    if run is None:
        return None
    counters = {k: v for k, v in (run.counters or {}).items() if k != "attribution_fingerprint"}
    return {
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": getattr(run.status, "value", run.status),
        "counters": counters,
    }


def status(session: Session) -> dict[str, Any]:
    """Decision 29, the data-health block `insights` (counts only): live cases, fact rows built, cases waiting and the
    oldest waiting since, the `READER_VERSION`, the last runs of both jobs, categories not grouped and the unmapped
    cause-title names (phrases and cases)."""
    live = int(
        session.scalar(select(func.count()).select_from(Case).where(Case.merged_into_case_id.is_(None))) or 0
    )
    built = int(
        session.scalar(
            select(func.count())
            .select_from(InsightCaseFact)
            .join(Case, Case.id == InsightCaseFact.case_id)
            .where(Case.merged_into_case_id.is_(None))
        )
        or 0
    )
    waiting, oldest = dirty_count(session)
    active_groups = select(InsightGroup.id).where(InsightGroup.is_active.is_(True))
    not_grouped = int(
        session.scalar(
            select(func.count(func.distinct(InsightSubjectCategory.category_code))).where(
                (InsightSubjectCategory.group_id.is_(None))
                | (InsightSubjectCategory.group_id.not_in(active_groups))
            )
        )
        or 0
    )
    unmapped = unmapped_phrases(session)
    unmapped_cases = 0
    if unmapped:
        unmapped_cases = int(
            session.scalar(
                text(
                    "SELECT count(*) FROM insight_case_facts f JOIN cases c ON c.id = f.case_id "
                    "WHERE c.merged_into_case_id IS NULL AND f.title_phrases && CAST(:p AS varchar[])"
                ),
                {"p": [p for p, _ in unmapped]},
            )
            or 0
        )
    bases = {
        b: int(n)
        for b, n in session.execute(
            text(
                "SELECT b, count(*) FROM insight_case_facts f JOIN cases c ON c.id = f.case_id "
                "CROSS JOIN LATERAL unnest(f.state_basis) AS b WHERE c.merged_into_case_id IS NULL GROUP BY b"
            )
        ).all()
    }
    return {
        "live_cases": live,
        "facts_built": built,
        "waiting": waiting,
        "oldest_waiting_since": oldest,
        "reader_version": R.READER_VERSION,
        "state_bases": {b: bases.get(b, 0) for b in ("party", "officer", "counsel", "title", "writ")},
        "categories_not_grouped": not_grouped,
        "unmapped_phrases": len(unmapped),
        "unmapped_phrase_cases": unmapped_cases,
        # design cause-title-signal-review-advisories, decision 12: the cases waiting for the drain (back to 0)
        "named_rescore_waiting": marked_count(session),
        "last_refresh": _last_run(session, JOB_REFRESH),
        "last_rebuild": _last_run(session, JOB_REBUILD),
    }
