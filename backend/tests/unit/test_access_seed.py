"""The default type matrix after design alerts-visibility-roles (decisions 13 and 17): the department head recalls
files, the Auditor has no Case Assistant and reads private records State-wide, and State oversight and the central
operator do not."""

from __future__ import annotations

from aslms.domain.reference import Permission as P
from aslms.domain.reference import Role
from aslms.services.access_seed import DEFAULT_MATRIX, PERMISSION_LABELS


def test_default_matrix_head_recalls_auditor_has_no_assistant_and_private_sight():
    assert P.CUSTODY_RECALL in DEFAULT_MATRIX[Role.DEPT_HEAD]
    assert P.CUSTODY_RECALL in DEFAULT_MATRIX[Role.DEPT_ADMIN]
    auditor = DEFAULT_MATRIX[Role.AUDITOR]
    assert P.ASSISTANT_USE not in auditor
    assert {P.CASES_VIEW_ALL, P.AUDIT_VIEW, P.CASES_VIEW_PRIVATE_ALL} <= auditor
    assert {P.CASES_VIEW_SCOPE, P.DOCUMENTS_VIEW, P.DOCUMENTS_DOWNLOAD} <= auditor
    for role in (Role.STATE_OVERSIGHT, Role.CENTRAL_OPERATOR):
        assert P.CASES_VIEW_PRIVATE_ALL not in DEFAULT_MATRIX[role], role
        assert P.ASSISTANT_USE in DEFAULT_MATRIX[role], role
    holders = {role for role, functions in DEFAULT_MATRIX.items() if P.CASES_VIEW_PRIVATE_ALL in functions}
    assert holders == {Role.AUDITOR}
    label, description = PERMISSION_LABELS[P.CASES_VIEW_PRIVATE_ALL]
    assert label == "View private records State-wide" and P.CASES_VIEW_PRIVATE_ALL.module == "cases"
    assert description.startswith("With View all cases")
