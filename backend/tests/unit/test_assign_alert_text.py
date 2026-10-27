"""Design claim-assign-wording, decision 7: the rendered ownership alert texts say "assigned"."""

from types import SimpleNamespace

from aslms.domain.reference import AlertKind
from aslms.services.alert_rules import render_alert


def _case():
    return SimpleNamespace(ref_no="ASLMS/GHC/CASE/2026/000001", cnr=None, case_number=None, title="A v B")


def test_assign_alert_title_and_body():
    title, body = render_alert(
        AlertKind.OWNERSHIP,
        _case(),
        {"event": "allotted", "officer_name": "Edu Off1", "actor_name": "Edu Admin"},
    )
    assert title.startswith("Case assigned:") and body == "Assigned to Edu Off1 by Edu Admin."


def test_assign_alert_falls_back_to_unit_then_your_unit():
    assert render_alert(AlertKind.OWNERSHIP, _case(), {"event": "allotted", "unit_code": "DSE"})[
        1
    ].startswith("Assigned to DSE by")
    assert "Assigned to your unit" in render_alert(AlertKind.OWNERSHIP, _case(), {"event": "allotted"})[1]


def test_take_over_body_says_assigned():
    _, body = render_alert(
        AlertKind.OWNERSHIP, _case(), {"event": "case_taken_over", "to_user_name": "Edu Off2"}
    )
    assert body == "The case assigned to you was taken over by Edu Off2."
