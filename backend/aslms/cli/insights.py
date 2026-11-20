"""`aslms insights` (design `state-insights`, "Services"): the readings of State Insights by rule, with no AI.

- `refresh [--all] [--dry-run]`: without `--all`, one run of the 10-minute job (at most `INSIGHTS_REFRESH_BATCH`
  dirty cases, then the department attribution when a mapping or an office changed); with `--all`, every live case
  rebuilt in batches, each its own transaction (`job_runs` `insights-refresh`). Both place first the seed case-type
  lines a case type lacks (`case_type_lines`). `--dry-run` counts the cases waiting and the lines that would be
  placed, and writes nothing. After a run, the cases whose cause-title readings changed are rescored by the matching
  engine (design `state-insights`, decision 36).
- `status`: the data-health block (counts only).
- `groups export`: the groupings as JSON (group codes and labels, category codes and case-type codes; no case text);
  `groups check`: the categories and case types not grouped (codes and labels of the court's masters only) and the
  seed case-type lines the next refresh would place (`case_types_seed_would_place`); read-only.

Counts only, never case text. No NAPIX call and no audit row: system work on derived data."""

from __future__ import annotations

import json

import typer
from rich import print as rprint
from sqlalchemy import select

from aslms.core.config import get_settings
from aslms.db.session import get_sessionmaker, session_scope
from aslms.domain.courts import CaseType
from aslms.domain.insights import InsightCaseTypeGroup, InsightGroup, InsightSubjectCategory
from aslms.services import insights_facts, insights_groups

insights_app = typer.Typer(no_args_is_help=True, help="State Insights readings: refresh, status, groups")
groups_app = typer.Typer(no_args_is_help=True, help="The Insights groupings: export, check")
insights_app.add_typer(groups_app, name="groups")


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


@insights_app.command("refresh")
def refresh(
    all_: bool = typer.Option(False, "--all", help="rebuild every live case, batch after batch"),
    dry_run: bool = typer.Option(False, "--dry-run", help="count the cases waiting; write nothing"),
    batch: int | None = typer.Option(None, "--batch", min=1, max=50000, help="cases per batch"),
) -> None:
    """Rebuild the readings of the cases waiting (or of every case with --all)."""
    size = batch or get_settings().insights_refresh_batch
    if dry_run:
        with session_scope() as s:
            report = insights_facts.refresh(s, batch=size, dry_run=True)
            s.rollback()
        rprint(report.as_dict())
        return
    if all_:
        report = insights_facts.rebuild(
            get_sessionmaker(),
            batch=size,
            job=insights_facts.JOB_REFRESH,
            echo=lambda m: rprint(f"[dim]{m}[/dim]"),
        )
        rprint(report.as_dict())
        return
    with session_scope() as s:
        report = insights_facts.refresh_if_free(s, batch=size)
    if report is None:
        rprint("[yellow]another refresh is running; nothing done[/yellow]")
        raise typer.Exit(1)
    out = report.as_dict()
    # design state-insights, decision 36: the cause-title signal follows the readings
    if report.named_changed_ids:
        out["rescored"] = insights_facts.rescore_changed(get_sessionmaker(), report.named_changed_ids).cases
    rprint(out)


@insights_app.command("status")
def status() -> None:
    """The readings' data-health block: live cases, rows built, cases waiting, bases, categories not grouped."""
    with session_scope() as s:
        rprint(_jsonable(insights_facts.status(s)))


@groups_app.command("export")
def groups_export() -> None:
    """The groupings as JSON: each group with its category codes or case-type codes."""
    with session_scope() as s:
        out: dict = {"subject": [], "family": []}
        cats: dict = {}
        for gid, code in s.execute(
            select(InsightSubjectCategory.group_id, InsightSubjectCategory.category_code).distinct()
        ).all():
            cats.setdefault(gid, set()).add(code)
        types: dict = {}
        for gid, code in s.execute(
            select(InsightCaseTypeGroup.group_id, CaseType.case_type_code).join(
                CaseType, CaseType.id == InsightCaseTypeGroup.case_type_id
            )
        ).all():
            types.setdefault(gid, set()).add(code)
        for g in s.scalars(select(InsightGroup).order_by(InsightGroup.kind, InsightGroup.sort_order)).all():
            members = cats.get(g.id, set()) if g.kind == "subject" else types.get(g.id, set())
            out[g.kind].append(
                {
                    "code": g.code,
                    "label": g.label,
                    "reserved": g.is_reserved,
                    "active": g.is_active,
                    "members": sorted(members),
                }
            )
    print(json.dumps(out, indent=2, ensure_ascii=False))


@groups_app.command("check")
def groups_check() -> None:
    """The categories with no active group, the case types with no line (read as Other) and the seed lines the next
    refresh would place. Writes nothing."""
    with session_scope() as s:
        active = set(s.scalars(select(InsightGroup.id).where(InsightGroup.is_active.is_(True))).all())
        loose = sorted(
            {
                (r.category_code, r.label)
                for r in s.scalars(select(InsightSubjectCategory)).all()
                if r.group_id is None or r.group_id not in active
            }
        )
        mapped = set(s.scalars(select(InsightCaseTypeGroup.case_type_id)).all())
        types = sorted(
            (ct.case_type_code, ct.short_name or ct.type_name)
            for ct in s.scalars(select(CaseType)).all()
            if ct.id not in mapped
        )
        seedable = insights_groups.seed_case_types_missing(s)
    rprint(
        {
            "categories_not_grouped": len(loose),
            "case_types_without_line": len(types),
            "case_types_seed_would_place": len(seedable),
        }
    )
    for code, label in loose:
        rprint(f"  category {code}: {label}")
    for code, name in types:
        rprint(f"  case type {code}: {name}")
    for code, name, group in seedable:
        rprint(f"  seed line to place: case type {code} ({name}) in {group}")
