"""Seed data for access control: the labels of the functions (`ref_permission`), the default type matrix
(`role_permissions`) from Table 1 of the plan, and the first super admin from `.env`.

Table 1 (plan, "Users and access"): State oversight — read-only view of all cases, State dashboards and
reports. Department head — all cases of the department and its directorates, approvals and oversight.
Department admin — manages the department's users, codes and keywords, reviews recommendations and claims.
Department officer — allotted cases, custody, notes, files, alerts. Directorate user — own directorate's
cases. Standing counsel — cases they appear in, notes and files shared with counsel. Central
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

PERMISSION_LABELS: dict[P, tuple[str, str]] = {
    P.USERS_VIEW: ("View users", "See the users of the offices in scope"),
    P.USERS_CREATE: ("Create users", "Create a user with a type in an office in scope"),
    P.USERS_EDIT: ("Edit users", "Change name, designation and contact details"),
    P.USERS_SET_TYPE: ("Change user type", "Change a user's type (role)"),
    P.USERS_ENABLE_DISABLE: ("Enable or disable users", "Switch a user's access on or off"),
    P.USERS_GRANT: ("Grant functions", "Grant or deny single functions to a user"),
    P.USERS_RESET_PASSWORD: ("Reset passwords", "Set a new password for a user"),
    P.USERS_PROPOSE_HEAD: (
        "Propose the head of department",
        "Request a head-of-department change for the super admin's approval, and follow its tickets",
    ),
    P.ACCESS_MANAGE_TYPES: ("Manage type matrix", "Switch functions on or off per user type"),
    P.OFFICES_MANAGE: ("Manage offices", "Create and edit departments and directorates"),
    P.ADMIN_COUNSEL_CODES: ("Counsel codes", "Map standing-counsel codes to departments"),
    P.ADMIN_KEYWORDS: ("Keywords and patterns", "Department keywords and name patterns for matching"),
    P.ADMIN_WATCHLIST: ("Watchlist", "Cases a department asks to follow"),
    P.ADMIN_MASTERS_SYNC: (
        "Sync court masters",
        "Queue a refresh of the NAPIX masters and run the connectivity check",
    ),
    P.ADMIN_NAPIX_REFETCH: (
        "Re-fetch court data",
        "Re-fetch a cause-list day, a case or an order PDF from NAPIX, and retry failed fetches",
    ),
    P.ADMIN_CONFIG: ("Configuration", "Change system configuration"),
    P.ADMIN_DESIGNATIONS: ("Designations", "Create and edit the State-wide designation list"),
    P.ADMIN_SCORING: ("Scoring settings", "Change the matching weights and recommendation thresholds"),
    P.ADMIN_TICKETS: (
        "Admin tickets",
        "Decide the requests that need the super admin's approval (reserved to the super admin)",
    ),
    P.ADMIN_SOURCETRACE: (
        "SourceTrace ingestion",
        "See the SourceTrace ingestion status and the failed documents, and retry them",
    ),
    P.ADMIN_DATA_LOAD: (
        "Manage the data load",
        "Start, pause and order the backdated NAPIX load, fetch single cases from the court, and check duplicates",
    ),
    P.ADMIN_SERVICE_HEALTH: (
        "System health",
        "See whether the court APIs and ASLMS's services are working, and test a court API with one live call",
    ),
    P.CASES_VIEW_SCOPE: ("View cases in scope", "Cases of the offices the user belongs to"),
    P.CASES_VIEW_ALL: ("View all cases", "Every case across all departments"),
    P.CASES_SEARCH_COURT: ("Search the court", "Search NAPIX by case number, party or advocate"),
    P.CASES_CLAIM: ("Claim cases", "Claim a recommended or unclaimed case for the department"),
    P.CASES_DISMISS: ("Dismiss recommendations", "Dismiss a recommendation as not ours"),
    P.CASES_SUGGEST_ELSEWHERE: ("Suggest another department", "Pass a recommendation to another department"),
    P.CASES_TRANSFER_REQUEST: ("Request transfer", "Ask another department to take a case"),
    P.CASES_TRANSFER_DECIDE: ("Decide transfers", "Accept or decline a transfer request"),
    P.CASES_ALLOT: ("Allot cases", "Allot a case to an officer"),
    P.CASES_RELEASE: ("Stop watching", "End the department's watcher role on a case"),
    P.CASES_TAKE_OVER: (
        "Take over a case",
        "Take over a case allotted to a colleague in the same department",
    ),
    P.CUSTODY_MOVE: ("Move custody", "Send a file held by an office (no officer) on to an officer"),
    P.CUSTODY_RECALL: (
        "Recall files",
        "Call a case of the own department back from wherever it is held",
    ),
    P.CUSTODY_TRACK: (
        "Track pending files",
        "Pending and overdue files of the own department, wherever they are held, with their alerts",
    ),
    P.REQUESTS_SEND: ("Send requests (retired)", "Retired: sending the file replaces requests"),
    P.REQUESTS_ANSWER: ("Answer requests (retired)", "Retired: sending the file replaces requests"),
    P.STAGES_SET: ("Set case stage", "Record the lifecycle stage of a case"),
    P.NOTES_ADD: ("Add notes", "Add a note to the case notes trail"),
    P.NOTES_VIEW_COUNSEL_SHARED: ("View counsel-shared notes", "Notes and files shared with counsel"),
    P.NOTES_VIEW_PRIVATE_OFFICE: ("View office-private notes", "Notes private to the user's office"),
    P.DOCUMENTS_UPLOAD: ("Upload documents", "Upload court filings and internal documents"),
    P.DOCUMENTS_VIEW: ("View documents", "Open documents, subject to their visibility"),
    P.DOCUMENTS_DOWNLOAD: ("Download documents", "Download documents, subject to their visibility"),
    P.ALERTS_ACKNOWLEDGE: ("Acknowledge alerts", "Acknowledge and close alerts"),
    P.NEXT_DATES_REVIEW: (
        "Review next dates",
        "Confirm or reject next dates read from orders, and enter next dates by hand",
    ),
    P.REPORTS_DEPARTMENT: ("Department reports", "Reports for the user's department"),
    P.REPORTS_STATE: ("State reports", "Reports across all departments"),
    P.DASHBOARD_STATE: ("State dashboard", "State-level dashboards"),
    P.ASSISTANT_USE: ("Case Assistant", "Ask the Case Assistant (through SourceTrace)"),
    P.AUDIT_VIEW: ("View audit log", "Read the audit log"),
}

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
    Role.DEPT_HEAD: _CASE_WORK | _OWNERSHIP | {P.REPORTS_DEPARTMENT, P.USERS_VIEW, P.CUSTODY_TRACK},
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
    Role.AUDITOR: _READ_CASES | {P.CASES_VIEW_ALL, P.AUDIT_VIEW},
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
