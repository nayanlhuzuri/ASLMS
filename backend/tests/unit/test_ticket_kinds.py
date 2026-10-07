"""The admin ticket registry without a database (design `user-memberships`, decisions 16-18, 20): every kind has
a handler and a seed row, the head-change payload refuses malformed requests, `admin.tickets` is reserved, and
the supporting documents are internal."""

from __future__ import annotations

import uuid

import pytest

from aslms.domain.reference import REF_TABLES, DocType, Permission, TicketKind
from aslms.services import tickets
from aslms.services.access import RESERVED_FUNCTIONS
from aslms.services.seed import DOC_GROUP

MID = str(uuid.uuid4())
FP = "0" * 64


def valid(op: str) -> dict:
    out = {"operation": op, "department_code": "EDU"}
    if op in ("set", "replace"):
        out["incoming"] = {"membership_id": MID}
    if op in ("replace", "end"):
        out["outgoing"] = {"mode": "retype"}
    return out


def test_every_kind_has_a_handler_and_a_seed_row():
    assert set(tickets.KINDS) == set(TicketKind)
    assert REF_TABLES["ref_ticket_kind"][1] is TicketKind


@pytest.mark.parametrize("op", ["set", "replace", "end"])
def test_valid_payloads(op):
    p = tickets.HeadChange.validate(valid(op))
    assert p.operation == op


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "promote", "department_code": "EDU", "incoming": {"membership_id": MID}},
        {**valid("set"), "outgoing": {"mode": "retype"}},  # set with an outgoing part
        {"operation": "replace", "department_code": "EDU", "incoming": {"membership_id": MID}},  # no outgoing
        {"operation": "end", "department_code": "EDU"},  # no outgoing
        {**valid("end"), "incoming": {"membership_id": MID}},  # end names no incoming head
        {**valid("replace"), "outgoing": {"mode": "retype", "role_to": "dept_admin"}},
        {**valid("replace"), "outgoing": {"mode": "retype", "role_to": "super_admin"}},
        {**valid("replace"), "outgoing": {"mode": "exit", "reason": "transferred"}},  # no assignment list
        {
            **valid("replace"),
            "outgoing": {"mode": "exit", "assignments": [], "reason": "transferred"},
        },  # no fp
        {**valid("set"), "incoming": {}},  # neither a membership nor an e-mail
        {**valid("set"), "incoming": {"membership_id": MID, "email": "x@example.org"}},  # both
    ],
)
def test_malformed_payloads_are_refused(payload):
    with pytest.raises(tickets.TicketError) as exc:
        tickets.HeadChange.validate(payload)
    assert exc.value.code == "bad_field"


def test_exit_with_a_complete_shape_is_accepted():
    p = tickets.HeadChange.validate(
        {
            **valid("replace"),
            "outgoing": {
                "mode": "exit",
                "assignments": [{"key": f"file:{MID}:{MID}", "to_membership": MID}],
                "items_fingerprint": FP,
                "reason": "transferred to Health",
            },
        }
    )
    assert p.outgoing.mode == "exit" and len(p.outgoing.assignments) == 1


def test_admin_tickets_is_reserved():
    assert Permission.ADMIN_TICKETS in RESERVED_FUNCTIONS


def test_documents_are_internal_and_head_change_takes_government_orders():
    for kind in tickets.KINDS.values():
        for dt in kind.doc_types:
            assert DOC_GROUP.get(dt, "internal") == "internal"
    assert tickets.HeadChange.doc_types == {DocType.GOVERNMENT_ORDER}
