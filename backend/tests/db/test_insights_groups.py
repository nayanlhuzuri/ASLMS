"""The Insights groupings (design `state-insights`, decisions 14 to 16, "Tests", `test_insights_groups.py`): the
reserved function, audited creates and updates, reserved groups (service and trigger), one audit row per regrouped
line, the composite key and that a change takes effect without a rebuild."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from aslms.core.clock import today_ist
from aslms.domain.events import AuditLog
from aslms.domain.insights import InsightGroup, InsightSubjectCategory
from aslms.domain.org import PermissionEffect
from aslms.domain.reference import Permission
from aslms.services import access, insights, insights_groups
from aslms.services import insights_filters as F
from aslms.services import insights_scope as sc
from aslms.services.access import Forbidden, ReservedFunction
from aslms.services.insights_groups import GroupsError
from tests.db import insights_support as ins

STATE = ("THE STATE OF ASSAM",)


def _audit(s, action: str) -> list[AuditLog]:
    return list(s.scalars(sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)))


def test_reserved_function_super_admin_only(world):
    with world.Session() as s:
        assert access.has(s, world.user(s, "root"), Permission.ADMIN_INSIGHTS_GROUPS)
        for key in ("oversight", "edu_admin", "edu_head", "central_op", "edu_auditor"):
            with pytest.raises(Forbidden):
                insights_groups.list_groups(s, world.user(s, key), "subject")
        actor, root = world.actor(s, "root")
        with pytest.raises(ReservedFunction):
            access.set_override(
                s,
                actor,
                root,
                world.membership(s, "oversight"),
                Permission.ADMIN_INSIGHTS_GROUPS,
                PermissionEffect.GRANT,
            )
        s.rollback()


def test_group_create_update_audited(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        g = insights_groups.create_group(
            s, actor, root, kind="subject", code="forest", label="Forest and Wildlife"
        )
        assert g.sort_order == 160 and not g.is_reserved
        with pytest.raises(GroupsError) as exc:
            insights_groups.create_group(s, actor, root, kind="subject", code="forest", label="Other Label")
        assert exc.value.code == "code_taken" and exc.value.http_status == 409
        with pytest.raises(GroupsError) as exc:
            insights_groups.create_group(
                s, actor, root, kind="subject", code="forest2", label="forest AND wildlife"
            )
        assert exc.value.code == "label_taken"
        with pytest.raises(GroupsError) as exc:
            insights_groups.create_group(s, actor, root, kind="family", code="Bad Code", label="X")
        assert exc.value.code == "bad_code"
        insights_groups.update_group(s, actor, root, g, label="Forests", sort_order=5)
        insights_groups.update_group(s, actor, root, g, label="Forests")  # nothing changed: nothing written
        insights_groups.update_group(s, actor, root, g, is_active=False)
        assert not g.is_active and g.deactivated_at is not None
        created = _audit(s, "insights.group_created")
        updated = _audit(s, "insights.group_updated")
        assert len(created) == 1 and created[0].after["code"] == "forest"
        assert (
            len(updated) == 2
            and updated[0].before["label"] == "Forest and Wildlife"
            and updated[0].after["sort_order"] == 5
        )
        groups = insights_groups.list_groups(s, root, "subject")
        assert groups[0]["code"] == "forest" and len(groups) == 16
        s.rollback()


def test_reserved_group_cannot_deactivate_or_recode(world):
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        ia = insights_groups.group_by_code(s, "family", "ia")
        with pytest.raises(GroupsError) as exc:
            insights_groups.update_group(s, actor, root, ia, is_active=False)
        assert exc.value.code == "reserved_group"
        insights_groups.update_group(
            s, actor, root, ia, label="Applications in a Case"
        )  # the label can change
        s.flush()
        with pytest.raises(DBAPIError):
            with s.begin_nested():
                s.execute(sa.update(InsightGroup).where(InsightGroup.id == ia.id).values(code="ia2"))
        with pytest.raises(DBAPIError):
            with s.begin_nested():
                s.execute(sa.update(InsightGroup).where(InsightGroup.id == ia.id).values(is_reserved=False))
        with pytest.raises(IntegrityError):
            with s.begin_nested():
                s.execute(
                    sa.update(InsightGroup)
                    .where(InsightGroup.id == ia.id)
                    .values(is_active=False, deactivated_at=sa.func.now())
                )
        s.rollback()


def test_category_regroup_one_audit_per_change(world):
    with world.Session() as s:
        ins.case_types(s)
        actor, root = world.actor(s, "root")
        changed = insights_groups.set_categories(
            s, actor, root, [(10023, "education"), (10024, "service_state"), (10025, None)]
        )
        assert [c["code"] for c in changed] == [10023, 10025]  # 10024 already in service_state
        rows = _audit(s, "insights.category_grouped")
        assert (
            len(rows) == 2
            and rows[0].before["group"] == "service_state"
            and rows[0].after["group"] == "education"
        )
        cats = {c["code"]: c for c in insights_groups.list_categories(s, root, group="not_grouped")}
        assert set(cats) == {10025}
        with pytest.raises(GroupsError) as exc:
            insights_groups.set_categories(s, actor, root, [(10023, "writ")])
        assert exc.value.code == "bad_group"
        types = {t["code"]: t for t in insights_groups.list_case_types(s, root)}
        assert types[220]["group"] == "ia" and types[142]["group"] == "contempt"
        changed = insights_groups.set_case_types(s, actor, root, [(types[171]["id"], "criminal_petition")])
        assert (
            changed[0]["group"] == "criminal_petition" and len(_audit(s, "insights.case_type_grouped")) == 1
        )
        s.rollback()


def test_composite_fk_refuses_family_group_for_category(world):
    with world.Session() as s:
        writ = insights_groups.group_by_code(s, "family", "writ")
        row = s.scalars(sa.select(InsightSubjectCategory)).first()
        with pytest.raises(DBAPIError):
            with s.begin_nested():
                s.execute(
                    sa.update(InsightSubjectCategory)
                    .where(InsightSubjectCategory.id == row.id)
                    .values(group_id=writ.id)
                )
        s.rollback()


def test_change_takes_effect_without_rebuild(world):
    with world.Session() as s:
        c = ins.case(s, respondents=STATE)
        ins.build(s, c)
        actor, root = world.actor(s, "root")
        scope = sc.resolve(s, root, "state", None)

        def subjects():
            f = F.parse(s, scope, today=today_ist())
            return {r["key"]: r["count"] for r in insights.overview(s, root, f, scope)["subjects"]}

        assert subjects()["service_state"] == 1
        insights_groups.set_categories(s, actor, root, [(10023, "education")])
        assert subjects()["education"] == 1 and subjects()["service_state"] == 0
        g = insights_groups.group_by_code(s, "subject", "education")
        insights_groups.update_group(s, actor, root, g, is_active=False)
        assert subjects()["not_grouped"] == 1  # a deactivated group's categories read as Not Grouped
        s.rollback()


def test_sort_order_bounds(world):
    """Design state-insights-review-advisories, decision 6: a whole number from 0 to 10,000, refused with 400
    `bad_sort_order` (never a 500 from the integer column); the automatic order stops at 10,000."""
    with world.Session() as s:
        actor, root = world.actor(s, "root")
        for value in (-1, 10_001, 2**40, True, "5"):
            with pytest.raises(GroupsError) as exc:
                insights_groups.create_group(
                    s, actor, root, kind="subject", code="forest", label="Forest", sort_order=value
                )
            assert exc.value.code == "bad_sort_order" and exc.value.http_status == 400, value
        low = insights_groups.create_group(
            s, actor, root, kind="subject", code="low", label="Low", sort_order=0
        )
        top = insights_groups.create_group(
            s, actor, root, kind="subject", code="top", label="Top", sort_order=insights_groups.SORT_ORDER_MAX
        )
        assert (low.sort_order, top.sort_order) == (0, 10_000)
        auto = insights_groups.create_group(s, actor, root, kind="subject", code="auto", label="Auto")
        assert auto.sort_order == 10_000  # max + 10, capped
        for value in (-1, 10_001, 2**40):
            with pytest.raises(GroupsError) as exc:
                insights_groups.update_group(s, actor, root, low, sort_order=value)
            assert exc.value.code == "bad_sort_order"
        assert low.sort_order == 0
        insights_groups.update_group(s, actor, root, low, sort_order=10_000)
        assert low.sort_order == 10_000
        s.rollback()


def test_group_line_counts_like_the_list(world):
    with world.Session() as s:
        cases = [ins.case(s, respondents=STATE) for _ in range(2)]
        ins.build(s, *cases)
        root = world.user(s, "root")
        g = insights_groups.group_by_code(s, "subject", "service_state")
        line = insights_groups.group_line(s, g)
        assert line == next(i for i in insights_groups.list_groups(s, root, "subject") if i["id"] == g.id)
        assert line["cases"] == 2 and line["pending"] == 2 and line["members"] > 0
        s.rollback()
