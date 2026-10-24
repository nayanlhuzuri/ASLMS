"""`aslms/db/migration_audit.py` (design `followups-oct`, decision 19b): a reference-data migration's audit row is
written once per application, a recorded downgrade starts a new application, and event keys carry the application
counter so a real re-application raises its events again. Run on a rolled-back transaction with a revision no
migration uses."""

from __future__ import annotations

import sqlalchemy as sa

from aslms.db import migration_audit as ma

REV = "0999"  # no real migration


def _rows(bind, action: str, key: str) -> int:
    return int(
        bind.execute(
            sa.text("SELECT count(*) FROM audit_log WHERE action = :a AND after->>'migration_key' = :k"),
            {"a": action, "k": key},
        ).scalar()
    )


def test_audit_once_writes_once_per_application(session):
    bind = session.connection()
    kw = dict(revision=REV, entity_type="access_rule", after={"rule": "example"})
    assert ma.audit_once(bind, "access.rule_changed", "rule:example", **kw) is True
    assert ma.audit_once(bind, "access.rule_changed", "rule:example", **kw) is False, (
        "a repeat writes nothing"
    )
    assert ma.audit_once(bind, "access.rule_kept", "rule:example", **kw) is True, (
        "another action is its own row"
    )
    assert _rows(bind, "access.rule_changed", "rule:example") == 1
    ma.record_downgrade(bind, REV, "0998")
    assert ma.audit_once(bind, "access.rule_changed", "rule:example", **kw) is True, (
        "a re-application is recorded"
    )
    assert ma.audit_once(bind, "access.rule_changed", "rule:example", **kw) is False
    assert _rows(bind, "access.rule_changed", "rule:example") == 2
    row = bind.execute(
        sa.text(
            "SELECT actor_name, after FROM audit_log WHERE action = 'access.rule_changed' "
            "ORDER BY created_at DESC LIMIT 1"
        )
    ).one()
    assert row.actor_name == f"migration {REV}"
    assert row.after == {"rule": "example", "migration": REV, "migration_key": "rule:example"}


def test_a_downgrade_of_another_revision_is_not_a_new_application(session):
    bind = session.connection()
    assert ma.audit_once(bind, "access.rule_changed", "k", revision=REV, entity_type="access_rule")
    ma.record_downgrade(bind, "1005", "1004")  # above REV: REV stays applied
    assert ma.application_no(bind, REV) == 1
    assert not ma.audit_once(bind, "access.rule_changed", "k", revision=REV, entity_type="access_rule")


def test_event_key_differs_after_a_downgrade_and_reapply(session):
    bind = session.connection()
    first = ma.event_key(REV, ma.application_no(bind, REV), "dept_head", "custody.recall")
    assert first == f"{REV}:1:dept_head:custody.recall"
    ma.record_downgrade(bind, REV, None)  # down to the base
    second = ma.event_key(REV, ma.application_no(bind, REV), "dept_head", "custody.recall")
    assert second == f"{REV}:2:dept_head:custody.recall" and second != first
