"""Migrations are an explicit step (design deployment-checklist, decision 12). `aslms ops db-guard`, in the Compose
`init` service, compares the database's Alembic revision with the code's head:

- `fresh` (no revision and no table in `public` other than `alembic_version`): runs `alembic upgrade head`, so the
  first installation is still one command;
- `at_head`: nothing;
- `behind` (a known older revision): exit 3, "run migrate";
- `ahead` (a revision this build does not know, or tables without a revision): exit 4.

`aslms ops migrate` (the `migrate` service, profile `ops`) is the only path for an upgrade: it refuses while the
application is connected, backs the database up first, migrates, seeds and writes the audit row `system.migrated`."""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

EXIT_BEHIND = 3
EXIT_AHEAD = 4
APP_ROLE = "aslms_app"


class DbState(enum.StrEnum):
    FRESH = "fresh"
    AT_HEAD = "at_head"
    BEHIND = "behind"
    AHEAD = "ahead"


@dataclass(frozen=True)
class GuardResult:
    state: DbState
    current: str | None
    head: str
    exit_code: int
    message: str


def classify(current: str | None, other_tables: int, head: str, known: set[str]) -> DbState:
    """The pure comparison: `known` holds every revision of this build's chain."""
    if current is None:
        return DbState.FRESH if other_tables == 0 else DbState.AHEAD
    if current == head:
        return DbState.AT_HEAD
    if current in known:
        return DbState.BEHIND
    return DbState.AHEAD


def outcome(state: DbState, current: str | None, head: str) -> GuardResult:
    """The exit code and the operator's message for a state."""
    if state is DbState.BEHIND:
        msg = (
            f"The database is at {current}; this build needs {head}. Stop the application and run: "
            "docker compose --profile ops run --rm migrate (it backs the database up first)."
        )
        return GuardResult(state, current, head, EXIT_BEHIND, msg)
    if state is DbState.AHEAD:
        what = current or "no revision (but it has tables)"
        msg = f"The database is newer than this build (it is at {what}; this build knows up to {head})."
        return GuardResult(state, current, head, EXIT_AHEAD, msg)
    if state is DbState.FRESH:
        return GuardResult(state, current, head, 0, f"A fresh database: migrating to {head}.")
    return GuardResult(state, current, head, 0, f"The database is at head ({head}).")


def alembic_config(url: str):
    """The Alembic configuration of this build: `alembic.ini` in the working directory (the image's `/app`), else next
    to the source tree."""
    from alembic.config import Config

    import aslms

    candidates = [Path.cwd() / "alembic.ini", Path(aslms.__file__).resolve().parents[1] / "alembic.ini"]
    ini = next((p for p in candidates if p.exists()), candidates[-1])
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def script_facts(cfg) -> tuple[str, set[str]]:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    return script.get_current_head(), {rev.revision for rev in script.walk_revisions()}


def read_revision(conn: Any) -> tuple[str | None, int]:
    """(the stored revision or None, the number of tables in `public` other than `alembic_version`)."""
    has_version = conn.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar()
    current = None
    if has_version:
        current = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
    other = conn.execute(
        text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
    ).scalar()
    return current, int(other or 0)


def state(conn: Any, cfg) -> GuardResult:
    head, known = script_facts(cfg)
    current, other = read_revision(conn)
    return outcome(classify(current, other, head, known), current, head)


def current_revision(url: str) -> str | None:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return read_revision(conn)[0]
    finally:
        engine.dispose()


def guard(url: str) -> GuardResult:
    """Decision 12: upgrade only a fresh database; report the others."""
    from alembic import command

    cfg = alembic_config(url)
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            result = state(conn, cfg)
    finally:
        engine.dispose()
    if result.state is DbState.FRESH:
        command.upgrade(cfg, "head")
    return result


def upgrade_head(url: str) -> None:
    from alembic import command

    command.upgrade(alembic_config(url), "head")


def app_sessions(conn: Any, role: str = APP_ROLE) -> int:
    """Sessions of the application role other than this one (`pg_stat_activity`)."""
    return int(
        conn.execute(
            text("SELECT count(*) FROM pg_stat_activity WHERE usename = :role AND pid <> pg_backend_pid()"),
            {"role": role},
        ).scalar()
        or 0
    )


def count_app_sessions(url: str, role: str = APP_ROLE) -> int:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return app_sessions(conn, role)
    finally:
        engine.dispose()


def is_superuser(conn: Any) -> bool:
    """Decision 5: is the connected role a superuser?"""
    return bool(conn.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar())


SUPERUSER_REFUSAL = "refusing to run as a database superuser"


def refuse_superuser(url: str, *, is_prod: bool) -> None:
    """In production a process that serves the application exits when its connection is a superuser (decision 5).
    Raises `SystemExit(1)` after logging the refusal; outside production it does nothing."""
    import logging

    if not is_prod:
        return
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            superuser = is_superuser(conn)
    finally:
        engine.dispose()
    if superuser:
        logging.getLogger("aslms.ops").error(SUPERUSER_REFUSAL)
        print(SUPERUSER_REFUSAL, file=sys.stderr, flush=True)  # also when logging is not configured yet
        raise SystemExit(1)


def write_migrated_audit(session: Any, before: str | None, after: str | None, backup: str | None) -> Any:
    """The audit row of an explicit migration (decision 12): system actor `ops`."""
    from aslms.services.audit import Actor, write_audit

    return write_audit(
        session,
        Actor.system("ops"),
        "system.migrated",
        "database",
        None,
        before={"revision": before},
        after={"revision": after, "backup": backup},
    )
