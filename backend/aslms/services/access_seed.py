"""Seed data for access control: the labels of the functions (`ref_permission`), the default type matrix
(`role_permissions`) from Table 1 of the plan, and the first super admin from `.env`.

Table 1 (plan, "Users and access"): State oversight — read-only view of all cases, State dashboards and
reports. Department head — all cases of the department and its directorates, approvals and oversight.
Department admin — manages the department's users, codes and keywords, reviews recommendations and claims.
Department officer — allotted cases, custody, notes and documents, alerts. Directorate user — own directorate's
cases. Standing counsel — cases they appear in, notes and documents shared with counsel. Central
operator — unclaimed cases and data quality. Auditor — read-only case records and the audit log. The referral
reviewer (in the approved role list, not in Table 1) gets the reviewing functions of a department officer
without ownership or custody."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aslms.core.config import get_settings
from aslms.domain.org import Office, RolePermission, User
from aslms.domain.reference import RETIRED_PERMISSIONS, Role
from aslms.domain.reference import Permission as P

# design case-workspace-admin, decision 21: plain-language labels, the description one line under the switch
PERMISSION_LABELS: dict[P, tuple[str, str]] = {
    P.USERS_VIEW: ("See users", "See the people of the offices you look after."),
    P.USERS_CREATE: (
        "Add users",
        "Create a sign-in for a new officer, with a user type, in an office you look after.",
    ),
    P.USERS_EDIT: ("Edit user details", "Change a person's name, designation and contact details."),
    P.USERS_SET_TYPE: ("Change a user's type", "Move a person to another user type."),
    P.USERS_ENABLE_DISABLE: (
        "Turn sign-in on or off",
        "Stop or restore a person's access; nothing they did is deleted.",
    ),
    P.USERS_GRANT: (
        "Give or take single functions",
        "Switch one function on or off for one person, within your own functions.",
    ),
    P.USERS_RESET_PASSWORD: ("Reset passwords", "Set a new password for a person."),
    P.USERS_PROPOSE_HEAD: (
        "Propose a new head",
        "Ask the super admin to change the head of a department, and follow the ticket.",
    ),
    P.ACCESS_MANAGE_TYPES: ("Change user types", "Switch functions on or off for a whole user type."),
    P.OFFICES_MANAGE: ("Manage offices", "Add, rename, move and close departments and directorates."),
    P.ADMIN_DESIGNATIONS: ("Manage designations", "Keep the State-wide list of posts up to date."),
    P.CASES_VIEW_SCOPE: (
        "See the office's cases",
        "Cases owned by, allotted to, or sent to the offices you belong to.",
    ),
    P.CASES_VIEW_ALL: ("See all cases", "Every case in the State, in every department."),
    P.CASES_VIEW_PRIVATE_ALL: (
        "See private records too",
        "With See all cases: notes, documents and remarks kept private to an office.",
    ),
    P.CASES_SEARCH_COURT: (
        "Search the High Court",
        "Look up a case at the court by CNR, number, party, advocate or filing number.",
    ),
    P.CASES_CLAIM: ("Claim cases", "Take a recommended or unclaimed case for the department."),
    P.CASES_DISMISS: ("Dismiss recommendations", "Say a recommended case is not the department's."),
    P.CASES_SUGGEST_ELSEWHERE: (
        "Suggest another department",
        "Point a recommended case to the department it belongs to.",
    ),
    P.CASES_TRANSFER_REQUEST: ("Ask for a transfer", "Ask another department to take over a claimed case."),
    P.CASES_TRANSFER_DECIDE: ("Decide transfers", "Accept or refuse a transfer asked of the department."),
    P.CASES_ALLOT: ("Allot cases", "Give a case of the department to an officer to work on."),
    P.CASES_RELEASE: ("Stop watching", "End the department's watching role on a case."),
    P.CASES_TAKE_OVER: (
        "Take over a case",
        "Take over a case allotted to a colleague in the same department.",
    ),
    P.CUSTODY_MOVE: (
        "Send cases held by an office",
        "Send on a case that is with an office rather than an officer; whoever has a case can always send it.",
    ),
    P.CUSTODY_RECALL: ("Recall cases", "Call a case of the department back from whoever has it."),
    P.CUSTODY_TRACK: (
        "Track pending cases",
        "See every case of the department that is waiting on someone, with due and overdue alerts.",
    ),
    P.REQUESTS_SEND: ("Send requests (retired)", "Retired: sending the case replaces requests"),
    P.REQUESTS_ANSWER: ("Answer requests (retired)", "Retired: sending the case replaces requests"),
    P.STAGES_SET: ("Set the stage", "Record where the department's work on a case stands."),
    P.NOTES_ADD: ("Add notes", "Write notes on a case; a note is never edited, a correction is a new note."),
    P.NOTES_VIEW_COUNSEL_SHARED: (
        "Read notes shared with counsel",
        "See notes and documents marked for the Standing Counsel.",
    ),
    P.NOTES_VIEW_PRIVATE_OFFICE: ("Read office-only notes", "See notes kept private to your own office."),
    # the description row 14 (design assistant) set is kept
    P.ASSISTANT_USE: ("Use the Case Assistant", "Ask the Case Assistant about cases and court orders"),
    P.DOCUMENTS_VIEW: ("See documents", "Open documents you are allowed to see."),
    P.DOCUMENTS_UPLOAD: (
        "Upload documents",
        "Add court papers and internal documents (PDF, Word, images) to a case.",
    ),
    P.DOCUMENTS_DOWNLOAD: ("Download documents", "Save a copy of a document you are allowed to see."),
    P.ALERTS_ACKNOWLEDGE: ("Acknowledge alerts", "Mark an alert as seen and dealt with."),
    P.NEXT_DATES_REVIEW: ("Confirm next dates", "Confirm, reject or enter the next date read from an order."),
    P.REPORTS_DEPARTMENT: ("Department reports", "Run and download the department's reports."),
    P.REPORTS_STATE: ("State reports", "Run and download reports across all departments."),
    P.DASHBOARD_STATE: ("State dashboard", "See the State-wide dashboard."),
    P.AUDIT_VIEW: ("Read the audit log", "Search who did what, and when."),
    P.ADMIN_COUNSEL_CODES: ("Counsel codes", "Link standing-counsel codes to departments."),
    P.ADMIN_KEYWORDS: ("Keywords and name patterns", "Words and names that point a case to a department."),
    P.ADMIN_WATCHLIST: ("Watchlist", "Cases a department always wants to follow."),
    P.ADMIN_SCORING: (
        "Scoring weights and bands",
        "How strongly each signal counts, and the strong and possible bands.",
    ),
    P.ADMIN_MASTERS_SYNC: (
        "Refresh court masters",
        "Reload case types and benches from the court, and run the connection check.",
    ),
    P.ADMIN_NAPIX_REFETCH: (
        "Fetch court data again",
        "Fetch a cause list, a case or an order again from the court, and retry failed fetches.",
    ),
    P.ADMIN_CONFIG: ("System settings", "Change system settings."),
    P.ADMIN_SOURCETRACE: (
        "Case Assistant intake",
        "See which court orders and filings went to the Case Assistant, and retry failures.",
    ),
    P.ADMIN_DATA_LOAD: (
        "Data collection",
        "Start, pause and order the historical load, fetch single cases and check duplicates.",
    ),
    P.ADMIN_SERVICE_HEALTH: (
        "System health",
        "See whether the court APIs and ASLMS services work, and test a court API with one call.",
    ),
    P.ADMIN_TICKETS: (
        "Decide admin tickets",
        "Decide the requests that need the super admin (reserved to the super admin).",
    ),
}

# design case-workspace-admin, decision 26: the plain-language groups of the user-type page, in order; every active
# function is in exactly one group (tests/unit/test_permission_groups.py). Data in code, returned by the API.
PERMISSION_GROUPS: tuple[tuple[str, str, tuple[P, ...]], ...] = (
    (
        "people",
        "People and access",
        (
            P.USERS_VIEW,
            P.USERS_CREATE,
            P.USERS_EDIT,
            P.USERS_SET_TYPE,
            P.USERS_ENABLE_DISABLE,
            P.USERS_GRANT,
            P.USERS_RESET_PASSWORD,
            P.USERS_PROPOSE_HEAD,
            P.ACCESS_MANAGE_TYPES,
            P.OFFICES_MANAGE,
            P.ADMIN_DESIGNATIONS,
        ),
    ),
    (
        "cases",
        "Cases and ownership",
        (
            P.CASES_VIEW_SCOPE,
            P.CASES_VIEW_ALL,
            P.CASES_VIEW_PRIVATE_ALL,
            P.CASES_SEARCH_COURT,
            P.CASES_CLAIM,
            P.CASES_DISMISS,
            P.CASES_SUGGEST_ELSEWHERE,
            P.CASES_TRANSFER_REQUEST,
            P.CASES_TRANSFER_DECIDE,
            P.CASES_ALLOT,
            P.CASES_RELEASE,
            P.CASES_TAKE_OVER,
        ),
    ),
    (
        "case_work",
        "Case work",
        (
            P.CUSTODY_MOVE,
            P.CUSTODY_RECALL,
            P.CUSTODY_TRACK,
            P.STAGES_SET,
            P.NOTES_ADD,
            P.NOTES_VIEW_COUNSEL_SHARED,
            P.NOTES_VIEW_PRIVATE_OFFICE,
            P.ASSISTANT_USE,
        ),
    ),
    ("documents", "Documents", (P.DOCUMENTS_VIEW, P.DOCUMENTS_UPLOAD, P.DOCUMENTS_DOWNLOAD)),
    ("alerts", "Alerts", (P.ALERTS_ACKNOWLEDGE, P.NEXT_DATES_REVIEW)),
    ("reports", "Reports", (P.REPORTS_DEPARTMENT, P.REPORTS_STATE, P.DASHBOARD_STATE, P.AUDIT_VIEW)),
    (
        "administration",
        "Administration",
        (
            P.ADMIN_COUNSEL_CODES,
            P.ADMIN_KEYWORDS,
            P.ADMIN_WATCHLIST,
            P.ADMIN_SCORING,
            P.ADMIN_MASTERS_SYNC,
            P.ADMIN_NAPIX_REFETCH,
            P.ADMIN_CONFIG,
            P.ADMIN_SOURCETRACE,
            P.ADMIN_DATA_LOAD,
            P.ADMIN_SERVICE_HEALTH,
            P.ADMIN_TICKETS,
        ),
    ),
)


def permission_group(permission: P) -> tuple[str, str, int] | None:
    """(group code, group label, 1-based place in the group) of a function; None for a retired one."""
    for code, label, members in PERMISSION_GROUPS:
        if permission in members:
            return code, label, members.index(permission) + 1
    return None


_READ_CASES = {P.CASES_VIEW_SCOPE, P.DOCUMENTS_VIEW, P.DOCUMENTS_DOWNLOAD, P.ASSISTANT_USE}
_CASE_WORK = _READ_CASES | {
    P.CASES_SEARCH_COURT,
    P.CUSTODY_MOVE,
    P.STAGES_SET,
    P.NOTES_ADD,
    P.NOTES_VIEW_PRIVATE_OFFICE,
    P.NOTES_VIEW_COUNSEL_SHARED,
    P.DOCUMENTS_UPLOAD,
    P.ALERTS_ACKNOWLEDGE,
    P.NEXT_DATES_REVIEW,
    P.CASES_TAKE_OVER,
}
_OWNERSHIP = {
    P.CASES_CLAIM,
    P.CASES_DISMISS,
    P.CASES_SUGGEST_ELSEWHERE,
    P.CASES_TRANSFER_REQUEST,
    P.CASES_TRANSFER_DECIDE,
    P.CASES_ALLOT,
    P.CASES_RELEASE,
}
_DEPT_ADMIN = {
    P.USERS_VIEW,
    P.USERS_CREATE,
    P.USERS_EDIT,
    P.USERS_SET_TYPE,
    P.USERS_ENABLE_DISABLE,
    P.USERS_GRANT,
    P.USERS_RESET_PASSWORD,
    P.USERS_PROPOSE_HEAD,
    P.ADMIN_COUNSEL_CODES,
    P.ADMIN_KEYWORDS,
    P.ADMIN_WATCHLIST,
    P.REPORTS_DEPARTMENT,
}

DEFAULT_MATRIX: dict[Role, set[P]] = {
    Role.STATE_OVERSIGHT: _READ_CASES
    | {P.CASES_VIEW_ALL, P.DASHBOARD_STATE, P.REPORTS_STATE, P.REPORTS_DEPARTMENT, P.USERS_VIEW},
    # design alerts-visibility-roles, decision 17: the head recalls cases like the department admin
    Role.DEPT_HEAD: _CASE_WORK
    | _OWNERSHIP
    | {P.REPORTS_DEPARTMENT, P.USERS_VIEW, P.CUSTODY_TRACK, P.CUSTODY_RECALL},
    Role.DEPT_ADMIN: _CASE_WORK | _OWNERSHIP | _DEPT_ADMIN | {P.CUSTODY_RECALL, P.CUSTODY_TRACK},
    Role.DEPT_OFFICER: _CASE_WORK,
    Role.DIRECTORATE_USER: _CASE_WORK - {P.CASES_SEARCH_COURT},
    Role.REFERRAL_REVIEWER: _READ_CASES | {P.NOTES_ADD, P.STAGES_SET, P.ALERTS_ACKNOWLEDGE},
    Role.STANDING_COUNSEL: _READ_CASES | {P.NOTES_ADD, P.NOTES_VIEW_COUNSEL_SHARED, P.DOCUMENTS_UPLOAD},
    Role.CENTRAL_OPERATOR: _READ_CASES
    | {
        P.CASES_VIEW_ALL,
        P.CASES_SEARCH_COURT,
        P.CASES_SUGGEST_ELSEWHERE,
        P.ADMIN_MASTERS_SYNC,
        P.ADMIN_NAPIX_REFETCH,
        P.ADMIN_SOURCETRACE,
        P.ADMIN_WATCHLIST,
        P.REPORTS_STATE,
        P.USERS_VIEW,
    },
    # design alerts-visibility-roles, decision 17: no Case Assistant; private records State-wide (decision 13)
    Role.AUDITOR: (_READ_CASES - {P.ASSISTANT_USE})
    | {P.CASES_VIEW_ALL, P.AUDIT_VIEW, P.CASES_VIEW_PRIVATE_ALL},
}


def seed_matrix(session: Session, report) -> None:
    """One row per (type, function) for every type except super_admin (which always has everything). The rows of
    a retired function are switched off (design custody-workflow, decision 22)."""
    existing = {
        (
            str(r.role.value if isinstance(r.role, Role) else r.role),
            str(r.permission.value if isinstance(r.permission, P) else r.permission),
        )
        for r in session.scalars(select(RolePermission)).all()
    }
    for role, enabled in DEFAULT_MATRIX.items():
        for perm in P:
            if (role.value, perm.value) in existing:
                continue
            session.add(RolePermission(role=role, permission=perm, is_enabled=perm in enabled))
            report.add("role_permissions")
    for row in session.scalars(
        select(RolePermission).where(
            RolePermission.permission.in_(list(RETIRED_PERMISSIONS)), RolePermission.is_enabled.is_(True)
        )
    ).all():
        row.is_enabled = False
        report.add("role_permissions_retired")
    session.flush()


def seed_super_admin(session: Session, report, root_office: Office) -> User | None:
    """The first super admin, from ASLMS_SUPERADMIN_EMAIL / ASLMS_SUPERADMIN_PASSWORD; created only on a system
    with no active super admin (design `user-memberships`, decision 13: exactly one, replaced only from the CLI).
    The password is never changed on later runs and nothing secret is logged."""
    from aslms.services.memberships import super_admin_membership

    s = get_settings()
    if not s.aslms_superadmin_email or s.aslms_superadmin_password is None:
        return None
    email = s.aslms_superadmin_email.strip().lower()
    current = super_admin_membership(session)
    if current is not None:
        holder = session.get(User, current.user_id)
        if holder is not None and holder.email != email:
            report.notes.append(f"super admin exists ({holder.email}); .env not used")
        return holder
    user = session.scalar(select(User).where(User.email == email))
    if user is not None:
        return user
    from aslms.services.audit import Actor
    from aslms.services.users import create_user

    user = create_user(
        session,
        Actor.system("seed"),
        email=email,
        password=s.aslms_superadmin_password.get_secret_value(),
        full_name="Super Administrator",
        role=Role.SUPER_ADMIN,
        office=root_office,
        designation="Super Administrator",
        must_confirm_profile=True,
    )
    report.add("users")
    return user
