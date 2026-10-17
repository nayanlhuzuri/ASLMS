"""`case_search.items_for` (design `search-court-advocate-filing`, decision 11): the court-search results built in
one visibility query, the same items as `item_for` per case, in the given order."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import event

from aslms.services import case_search
from tests.db.report_support import own_directly
from tests.db.world import make_case


def _mixed(s, world):
    edu = make_case(s, pet="EDU OWNED")
    health = make_case(s, pet="HEALTH OWNED")
    pool = make_case(s, pet="IN THE POOL")
    fetched = make_case(s, pet="POOL WITH DETAILS")
    fetched.last_full_refresh_at = datetime.now(UTC)
    own_directly(s, world, edu, "EDU")
    own_directly(s, world, health, "HEALTH")
    s.flush()
    return [health, pool, edu, fetched]


class Counter:
    def __init__(self, session) -> None:
        self.n = 0
        self.engine = session.get_bind()

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._hit)
        return self

    def __exit__(self, *exc) -> None:
        event.remove(self.engine, "before_cursor_execute", self._hit)

    def _hit(self, *args) -> None:
        self.n += 1


def test_items_for_matches_item_for_in_order(world) -> None:
    with world.Session() as s:
        cases = _mixed(s, world)
        for key in ("edu_admin", "health_off", "dse_user", "root"):
            user = world.user(s, key)
            many = case_search.items_for(s, user, cases, match="advocate")
            one = [case_search.item_for(s, user, c, match="advocate") for c in cases]
            assert many == one, key
        edu_admin = world.user(s, "edu_admin")
        items = case_search.items_for(s, edu_admin, cases, match="advocate")
        assert [i["case"]["id"] for i in items] == [c.id for c in cases]
        assert [(i["visible"], i["in_pool"], i["dossier_status"]) for i in items] == [
            (False, False, "not_fetched"),
            (True, True, "not_fetched"),
            (True, False, "not_fetched"),
            (True, True, "fetched"),
        ]
        assert [i["claimable"] for i in items] == [False, True, False, True]
        assert [i["owner_office_code"] for i in items] == ["HEALTH", None, "EDU", None]
        assert {i["match"] for i in items} == {"advocate"}
        s.rollback()


def test_items_for_uses_a_constant_number_of_queries(world) -> None:
    with world.Session() as s:
        cases = _mixed(s, world) + [make_case(s, pet=f"MORE {n}") for n in range(20)]
        user = world.user(s, "edu_admin")
        case_search.items_for(s, user, cases[:1])  # warm the per-user lookups
        with Counter(s) as single:
            case_search.items_for(s, user, cases[:1])
        with Counter(s) as many:
            case_search.items_for(s, user, cases)
        with Counter(s) as per_case:
            for c in cases:
                case_search.item_for(s, user, c)
        assert many.n == single.n
        assert per_case.n >= len(cases) * single.n
        assert case_search.items_for(s, user, []) == []
        s.rollback()


def test_items_for_keeps_repeated_cases(world) -> None:
    with world.Session() as s:
        a, b, *_ = _mixed(s, world)
        user = world.user(s, "root")
        items = case_search.items_for(s, user, [a, b, a])
        assert [i["case"]["id"] for i in items] == [a.id, b.id, a.id]
        s.rollback()
