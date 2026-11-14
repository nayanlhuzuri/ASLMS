"""`aslms offices import` (design `offices-import`, decisions 7-22): the owner's workbook of departments, offices,
department heads, first department administrators and office heads, checked and then applied in one audited run.

- `read_workbook(data)` reads the two sheets ("Departments", "Offices Under Departments") by their header text, not
  by column letter; the formula and remark columns are never read. A bad file raises `ImportFileError`.
- `check(session, wb)` makes every check with read-only queries and returns an `ImportPlan`: the problems (errors
  block `--apply` for the whole file, notices do not, skips are rows left out or waiting), the planned actions and
  the counts. The rules are written against a small `Lookup` so they can be tested without a database.
- `fingerprint(data, plan)` is 12 hex characters of the sha256 of the file's bytes and the plan; `apply` refuses
  (`PlanChanged`) when the file or the database changed since the dry run the owner approved.
- `apply(...)` re-runs every check inside one transaction under a transaction-level advisory lock, then writes only
  through `offices`, `memberships`, `users` and `tickets`, in the order of decision 14, and writes one summary row
  `office_import.applied`. A second run with the same workbook matches everything and writes nothing.
- `run_apply(...)` commits, then sends the welcome mails (decision 18), so a rolled-back run e-mails nobody.

Personal details stay out of every message (decision 20): problems name the sheet, the row, the column and the office
code; an e-mail appears only masked; names and mobiles never. Nothing from a row is logged."""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from aslms.domain.courts import Court
from aslms.domain.org import Designation, Office, User
from aslms.domain.reference import OfficeKind, RefOfficeKind, RefRole, Role
from aslms.services import access, memberships, offices
from aslms.services.audit import Actor, write_audit
from aslms.services.mailer import mask_address
from aslms.services.offices import (
    DEPARTMENT_TIER_KINDS,
    MAX_PATH,
    OFFICE_CODE_MAX,
    OFFICE_CODE_RE,
    PLACEMENT,
    designation_code_from_name,
    normalised_name,
)
from aslms.services.users import EMAIL_RE, create_user

MAX_BYTES = 5 * 1024 * 1024
ZIP_SIGNATURE = b"PK\x03\x04"
HEADER_SCAN_ROWS = 10
LOCK_KEY = "aslms_offices_import"
USER_AGENT = "aslms offices import"

DEPT_SHEET = "Departments"
OFFICE_SHEET = "Offices Under Departments"
SHEET_SHORT = {DEPT_SHEET: "Departments", OFFICE_SHEET: "Offices"}

# the columns read, by header text (decision 8); `Website` is optional, every other one is required
DEPT_COLUMNS = {
    "no": "No.",
    "name": "Department Name (as on the site)",
    "website": "Website",
    "code": "Code",
    "include": "Include?",
    "head_name": "Head: Full Name",
    "head_designation": "Head: Designation",
    "head_email": "Head: Login E-mail",
    "head_mobile": "Head: Mobile (10 digits)",
    "head_has_login": "Head Already Has an ASLMS Login?",
    "admin_name": "Admin: Full Name",
    "admin_designation": "Admin: Designation",
    "admin_email": "Admin: Login E-mail",
    "admin_mobile": "Admin: Mobile (10 digits)",
    "admin_has_login": "Admin Already Has an ASLMS Login?",
}
OFFICE_COLUMNS = {
    "no": "No.",
    "parent": "Parent Department",
    "name": "Office Name",
    "website": "Website",
    "kind": "Office Type",
    "code": "Code",
    "include": "Include?",
    "head_name": "Office Head: Full Name",
    "head_designation": "Office Head: Designation",
    "head_email": "Office Head: Login E-mail",
    "head_mobile": "Office Head: Mobile (10 digits)",
    "head_type": "Office Head: User Type",
    "head_has_login": "Already Has an ASLMS Login?",
}
OPTIONAL_COLUMNS = frozenset({"website"})

# the workbook's own words for the office types (its Lists sheet), besides each kind's code and current label
KIND_WORDS = {
    "directorate / commissionerate": OfficeKind.DIRECTORATE,
    "directorate": OfficeKind.DIRECTORATE,
    "board / corporation": OfficeKind.BOARD_CORPORATION,
    "statutory authority / commission": OfficeKind.STATUTORY_AUTHORITY,
    "society / mission / project": OfficeKind.SOCIETY_MISSION,
    "institution": OfficeKind.INSTITUTION,
    "local body": OfficeKind.LOCAL_BODY,
    "autonomous council": OfficeKind.AUTONOMOUS_COUNCIL,
    "unit": OfficeKind.UNIT,
}
# decision 11: an office head is a Department Officer or a Directorate User (the workbook's words)
OFFICE_HEAD_TYPES = frozenset({Role.DEPT_OFFICER, Role.DIRECTORATE_USER})
TYPE_WORDS = {"directorate user": Role.DIRECTORATE_USER, "department officer": Role.DEPT_OFFICER}

ERROR, NOTICE, SKIP = "error", "notice", "skip"
_SPACES = re.compile(r"\s+")


class ImportFileError(ValueError):
    """The file cannot be read as the workbook (exit 2)."""


class PlanChanged(RuntimeError):
    """The fingerprint differs from the approved dry run: the file or the database changed (exit 3)."""


class ImportErrors(RuntimeError):
    """The re-check inside the transaction found errors (exit 1); nothing is written."""

    def __init__(self, plan: ImportPlan) -> None:
        super().__init__(f"{len(plan.errors)} error(s) in the workbook; nothing was imported")
        self.plan = plan


class NoSuperAdmin(RuntimeError):
    """There is no active Super Administrator to act as (exit 5)."""


# ------------------------------------------------------------------------------------------------ reading


def clean(value: Any) -> str:
    """A cell as trimmed text: non-breaking spaces read as spaces, runs of spaces collapsed, a whole number typed as
    a number (`9864012345` or `9864012345.0`) read as its digits."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return _SPACES.sub(" ", str(value).replace(" ", " ")).strip()


def _key(value: str) -> str:
    return clean(value).casefold()


@dataclass
class Person:
    """One person's cells on a row (all text, cleaned)."""

    full_name: str = ""
    designation: str = ""
    email: str = ""
    mobile: str = ""
    has_login: str = ""
    user_type: str = ""

    def cells(self) -> list[str]:
        return [self.full_name, self.designation, self.email, self.mobile, self.has_login, self.user_type]

    @property
    def empty(self) -> bool:
        return not any(self.cells())


@dataclass
class DeptRow:
    row: int
    name: str
    website: str
    code: str
    include: str
    head: Person
    admin: Person


@dataclass
class OfficeRow:
    row: int
    parent: str
    name: str
    website: str
    kind: str
    code: str
    include: str
    head: Person


@dataclass
class Workbook:
    sha256: str
    departments: list[DeptRow] = field(default_factory=list)
    offices: list[OfficeRow] = field(default_factory=list)


def _sheet(book, name: str):
    for ws in book.worksheets:
        if _key(ws.title) == _key(name):
            return ws
    raise ImportFileError(f'the sheet "{name}" is missing')


def _rows(ws, sheet: str, columns: dict[str, str]) -> Iterable[tuple[int, dict[str, str]]]:
    """The data rows below the header row (the row that starts with "No." within the first 10 rows), as
    {column key: cleaned text}, with their sheet row number."""
    it = ws.iter_rows(values_only=True)
    header_at, index = None, {}
    for n, values in enumerate(it, start=1):
        cells = [clean(v) for v in (values or ())]
        first = next((c for c in cells if c), "")
        if _key(first) == _key("No."):
            header_at = n
            wanted = {_key(h): k for k, h in columns.items()}
            for i, c in enumerate(cells):
                k = wanted.get(_key(c))
                if k is not None and k not in index:
                    index[k] = i
            break
        if n >= HEADER_SCAN_ROWS:
            break
    if header_at is None:
        raise ImportFileError(
            f'the sheet "{sheet}" has no header row starting with "No." in its first 10 rows'
        )
    missing = [columns[k] for k in columns if k not in index and k not in OPTIONAL_COLUMNS]
    if missing:
        raise ImportFileError(f'the sheet "{sheet}" has no column "{missing[0]}"')
    for n, values in enumerate(it, start=header_at + 1):
        values = values or ()
        yield n, {k: clean(values[i]) if i < len(values) else "" for k, i in index.items()}


def read_workbook(data: bytes) -> Workbook:
    """The two sheets as typed rows (decision 8). Refuses a file over 5 MB or one that is not a zip (an .xlsx is),
    and a workbook without the sheets or the headers. Empty rows (no name and no code) are skipped silently."""
    if len(data) > MAX_BYTES:
        raise ImportFileError("the file is larger than 5 MB")
    if not data.startswith(ZIP_SIGNATURE):
        raise ImportFileError("the file is not an Excel workbook (.xlsx)")
    import openpyxl  # defusedxml is installed, so openpyxl parses the XML defensively

    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ImportFileError(f"the file cannot be read as a workbook ({exc.__class__.__name__})") from exc
    try:
        wb = Workbook(sha256=hashlib.sha256(data).hexdigest())
        for n, r in _rows(_sheet(book, DEPT_SHEET), DEPT_SHEET, DEPT_COLUMNS):
            if not r["name"] and not r["code"]:
                continue
            wb.departments.append(
                DeptRow(
                    row=n,
                    name=r["name"],
                    website=r.get("website", ""),
                    code=r["code"],
                    include=r["include"],
                    head=Person(
                        r["head_name"],
                        r["head_designation"],
                        r["head_email"],
                        r["head_mobile"],
                        r["head_has_login"],
                    ),
                    admin=Person(
                        r["admin_name"],
                        r["admin_designation"],
                        r["admin_email"],
                        r["admin_mobile"],
                        r["admin_has_login"],
                    ),
                )
            )
        for n, r in _rows(_sheet(book, OFFICE_SHEET), OFFICE_SHEET, OFFICE_COLUMNS):
            if not r["name"] and not r["code"]:
                continue
            wb.offices.append(
                OfficeRow(
                    row=n,
                    parent=r["parent"],
                    name=r["name"],
                    website=r.get("website", ""),
                    kind=r["kind"],
                    code=r["code"],
                    include=r["include"],
                    head=Person(
                        r["head_name"],
                        r["head_designation"],
                        r["head_email"],
                        r["head_mobile"],
                        r["head_has_login"],
                        r["head_type"],
                    ),
                )
            )
    finally:
        book.close()
    return wb


# ------------------------------------------------------------------------------------------------ what the rules read


@dataclass(frozen=True)
class OfficeInfo:
    code: str
    name: str
    kind: str
    path: str
    parent_code: str | None
    is_active: bool


@dataclass(frozen=True)
class MemberInfo:
    office_code: str
    department_code: str | None
    role: str


@dataclass(frozen=True)
class LoginInfo:
    email: str
    is_active: bool
    is_super_admin: bool
    memberships: tuple[MemberInfo, ...] = ()


@dataclass(frozen=True)
class DesignationInfo:
    code: str
    name: str
    is_active: bool


class Lookup(Protocol):
    """What the checks read from the database (a fake in the unit tests)."""

    def root(self) -> OfficeInfo: ...
    def office(self, code: str) -> OfficeInfo | None: ...
    def children(self, parent_code: str) -> list[OfficeInfo]: ...
    def departments(self) -> list[OfficeInfo]: ...
    def court_code(self, code: str) -> bool: ...
    def login(self, email: str) -> LoginInfo | None: ...
    def designations(self) -> list[DesignationInfo]: ...
    def role_labels(self) -> dict[str, str]: ...
    def kind_labels(self) -> dict[str, str]: ...
    def head_email(self, department_code: str) -> str | None: ...
    def admin_email(self, department_code: str) -> str | None: ...


def _info(o: Office, parent_code: str | None = None) -> OfficeInfo:
    parts = o.path.split("/")
    return OfficeInfo(
        code=o.code,
        name=o.name,
        kind=o.kind.value if isinstance(o.kind, OfficeKind) else str(o.kind),
        path=o.path,
        parent_code=parent_code if parent_code is not None else (parts[-2] if len(parts) > 1 else None),
        is_active=bool(o.is_active),
    )


class DbLookup:
    """The `Lookup` on the database: read-only queries."""

    def __init__(self, session: Session) -> None:
        self.s = session

    def root(self) -> OfficeInfo:
        return _info(memberships.state_root(self.s))

    def office(self, code: str) -> OfficeInfo | None:
        o = offices.find_office(self.s, code)
        return _info(o) if o is not None else None

    def children(self, parent_code: str) -> list[OfficeInfo]:
        parent = offices.find_office(self.s, parent_code)
        if parent is None:
            return []
        rows = self.s.scalars(
            select(Office).where(Office.parent_id == parent.id, Office.is_active.is_(True))
        ).all()
        return [_info(o, parent.code) for o in rows]

    def departments(self) -> list[OfficeInfo]:
        rows = self.s.scalars(
            select(Office).where(Office.is_active.is_(True), Office.kind.in_(list(DEPARTMENT_TIER_KINDS)))
        ).all()
        return [_info(o) for o in rows if offices.tier_of(o) == "department"]

    def court_code(self, code: str) -> bool:
        return self.s.scalar(select(Court.id).where(Court.ref_code == code).limit(1)) is not None

    def login(self, email: str) -> LoginInfo | None:
        user = memberships.lookup(self.s, email)
        if user is None:
            return None
        ms = []
        for m in access.active_memberships(self.s, user):
            office = self.s.get(Office, m.office_id)
            dept = self.s.get(Office, m.department_id) if m.department_id else None
            role = m.role.value if isinstance(m.role, Role) else str(m.role)
            ms.append(MemberInfo(office.code, dept.code if dept else None, role))
        return LoginInfo(user.email, bool(user.is_active), access.is_super_admin(user), tuple(ms))

    def designations(self) -> list[DesignationInfo]:
        return [
            DesignationInfo(d.code, d.name, bool(d.is_active))
            for d in self.s.scalars(select(Designation)).all()
        ]

    def role_labels(self) -> dict[str, str]:
        return dict(self.s.execute(select(RefRole.code, RefRole.label)).all())

    def kind_labels(self) -> dict[str, str]:
        return dict(self.s.execute(select(RefOfficeKind.code, RefOfficeKind.label)).all())

    def _email(self, department_code: str, fn) -> str | None:
        dept = offices.find_office(self.s, department_code)
        m = fn(self.s, dept) if dept is not None else None
        return self.s.get(User, m.user_id).email if m is not None else None

    def head_email(self, department_code: str) -> str | None:
        return self._email(department_code, memberships.head_of)

    def admin_email(self, department_code: str) -> str | None:
        return self._email(department_code, memberships.admin_of)


# ------------------------------------------------------------------------------------------------ the plan


@dataclass
class Problem:
    sheet: str
    row: int | None
    column: str | None
    code: str
    severity: str
    message: str
    office_code: str | None = None

    def where(self) -> str:
        out = SHEET_SHORT.get(self.sheet, self.sheet)
        if self.row is not None:
            out += f" row {self.row}"
        if self.office_code:
            out += f" ({self.office_code})"
        if self.column:
            out += f", {self.column}"
        return out


@dataclass
class PersonRef:
    """A person the plan names: the login (by e-mail) and the designation of the new membership."""

    email: str
    designation: str  # the designation's name as stored (an existing one's own name, or the new one's)
    designation_code: str
    new_login: bool


@dataclass
class DeptAction:
    row: int
    code: str
    name: str
    website: str | None
    action: str  # create | match
    rename_to: str | None = None
    head: PersonRef | None = None
    head_action: str = "none"  # create_with | set | match | differs | none
    admin: PersonRef | None = None
    admin_action: str = "none"  # add | match | differs | none


@dataclass
class OfficeAction:
    row: int
    code: str
    name: str
    website: str | None
    kind: str
    parent_code: str
    action: str  # create | match
    rename_to: str | None = None
    head: PersonRef | None = None
    head_role: str | None = None
    head_action: str = "none"  # add | match | none


@dataclass
class NewLogin:
    email: str
    full_name: str
    mobile: str | None


@dataclass
class NewDesignation:
    code: str
    name: str


@dataclass
class ImportPlan:
    problems: list[Problem] = field(default_factory=list)
    departments: list[DeptAction] = field(default_factory=list)
    offices: list[OfficeAction] = field(default_factory=list)
    new_logins: list[NewLogin] = field(default_factory=list)
    matched_logins: list[str] = field(default_factory=list)
    new_designations: list[NewDesignation] = field(default_factory=list)

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == ERROR]

    @property
    def notices(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == NOTICE]

    @property
    def skips(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == SKIP]

    def counts(self) -> dict[str, Any]:
        d, o = self.departments, self.offices
        skipped: dict[str, int] = {}
        for p in self.skips:
            skipped[p.code] = skipped.get(p.code, 0) + 1
        return {
            "departments_created": sum(a.action == "create" for a in d),
            "departments_matched": sum(a.action == "match" for a in d),
            "departments_renamed": sum(a.rename_to is not None for a in d),
            "departments_no_head_yet": sum(a.action == "create" and a.head_action == "none" for a in d),
            "offices_created": sum(a.action == "create" for a in o),
            "offices_matched": sum(a.action == "match" for a in o),
            "offices_renamed": sum(a.rename_to is not None for a in o),
            "logins_created": len(self.new_logins),
            "logins_matched": len(self.matched_logins),
            "heads": sum(a.head_action in ("create_with", "set") for a in d),
            "admins": sum(a.admin_action == "add" for a in d),
            "office_heads": sum(a.head_action == "add" for a in o),
            "designations_created": len(self.new_designations),
            "rows_skipped": skipped,
        }

    @property
    def has_changes(self) -> bool:
        c = self.counts()
        keys = (
            "departments_created",
            "departments_renamed",
            "offices_created",
            "offices_renamed",
            "logins_created",
            "heads",
            "admins",
            "office_heads",
            "designations_created",
        )
        return any(c[k] for k in keys)

    def canonical(self) -> dict[str, Any]:
        """The actions only, in a stable form (the fingerprint's input)."""
        return {
            "departments": [asdict(a) for a in self.departments],
            "offices": [asdict(a) for a in self.offices],
            "new_logins": [asdict(a) for a in self.new_logins],
            "matched_logins": sorted(self.matched_logins),
            "new_designations": [asdict(a) for a in self.new_designations],
        }


def fingerprint(data: bytes | str, plan: ImportPlan) -> str:
    """12 hex characters of the sha256 of the file's bytes (or their sha256 hex) and the plan (decision 7)."""
    sha = data if isinstance(data, str) else hashlib.sha256(data).hexdigest()
    body = json.dumps(plan.canonical(), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{sha}\n{body}".encode()).hexdigest()[:12]


# ------------------------------------------------------------------------------------------------ the checks


def _include(value: str) -> str:
    """yes | no | wait (To Decide, blank or anything else)."""
    v = _key(value)
    if v == "yes":
        return "yes"
    if v == "no":
        return "no"
    return "wait"


def _placeholder(cell: str) -> bool:
    return ("[" in cell and "]" in cell) or bool(re.search(r"[xX]{4,}", cell)) or "…" in cell


def _parse_mobile(value: str) -> str | None:
    from aslms.services.profile import ProfileError, normalise_mobile

    try:
        return normalise_mobile(value)
    except ProfileError:
        return None


@dataclass
class _Mention:
    """One appearance of a person on a row."""

    sheet: str
    row: int
    office_code: str | None
    label: str  # column prefix: "Head", "Admin", "Office Head"
    person: Person
    incomplete_code: str  # head_partial for a department head, else person_incomplete


class _Checker:
    def __init__(self, lookup: Lookup, wb: Workbook) -> None:
        self.lk = lookup
        self.wb = wb
        self.plan = ImportPlan()
        self.root = lookup.root()
        self._logins: dict[str, LoginInfo | None] = {}
        self.designations = lookup.designations()
        self.taken_designation_codes = {d.code.upper() for d in self.designations}
        self.new_designations: dict[str, NewDesignation] = {}  # normalised name -> new designation
        self.mentions: dict[str, list[_Mention]] = {}  # e-mail -> mentions (valid e-mails only)
        self.planned: list[tuple[str, str, str, str, _Mention]] = []  # (email, dept, office, role, mention)
        self.codes_seen: dict[str, tuple[str, int]] = {}
        self.names_seen: dict[tuple[str, str], tuple[str, int]] = {}
        role_labels = lookup.role_labels()
        self.type_words = dict(TYPE_WORDS)
        for r in Role:
            self.type_words[r.value] = r
            if r.value in role_labels:
                self.type_words[_key(role_labels[r.value])] = r
        self.kind_words: dict[str, OfficeKind] = dict(KIND_WORDS)
        for code, label in lookup.kind_labels().items():
            try:
                kind = OfficeKind(code)
            except ValueError:
                continue
            self.kind_words[code] = kind
            self.kind_words[_key(label)] = kind

    # ------------------------------------------------------------------ problems
    def add(self, sheet, row, column, code, severity, message, office_code=None) -> None:
        self.plan.problems.append(Problem(sheet, row, column, code, severity, message, office_code))

    def login(self, email: str) -> LoginInfo | None:
        if email not in self._logins:
            self._logins[email] = self.lk.login(email)
        return self._logins[email]

    # ------------------------------------------------------------------ codes and names
    def check_code(self, sheet: str, row: int, raw: str) -> str | None:
        code = raw.strip().upper()
        if not code:
            self.add(sheet, row, "Code", "bad_code", ERROR, "the code is empty")
            return None
        if not OFFICE_CODE_RE.match(code):
            if re.fullmatch(r"[A-Z0-9][A-Z0-9-]+", code) and len(code) > OFFICE_CODE_MAX:
                self.add(
                    sheet,
                    row,
                    "Code",
                    "code_too_long",
                    ERROR,
                    f"the code has {len(code)} characters; a code is 2 to 17 characters because it is part of "
                    "every reference number the office issues",
                    code,
                )
            else:
                self.add(sheet, row, "Code", "bad_code", ERROR, offices.OFFICE_CODE_RULE, code)
            return None
        seen = self.codes_seen.get(code)
        if seen is not None:
            self.add(
                sheet,
                row,
                "Code",
                "duplicate_code_in_file",
                ERROR,
                f"the code is also used on {SHEET_SHORT[seen[0]]} row {seen[1]}",
                code,
            )
            return None
        self.codes_seen[code] = (sheet, row)
        return code

    def check_new_code(self, sheet: str, row: int, code: str, name: str, parent_code: str) -> bool:
        """A code not yet in the database: not a court's code, no active office of the same name under the parent,
        no other row of the same name under the parent."""
        ok = True
        if self.lk.court_code(code):
            self.add(
                sheet, row, "Code", "court_code", ERROR, f"{code} is a court's code in case numbers", code
            )
            ok = False
        norm = normalised_name(name)
        for other in self.lk.children(parent_code):
            if other.code != code and normalised_name(other.name) == norm:
                self.add(
                    sheet,
                    row,
                    "Code",
                    "possible_duplicate",
                    ERROR,
                    f"the office {other.code} under {parent_code} already has this name; use its code {other.code} "
                    "in this row instead of a new one",
                    code,
                )
                ok = False
        seen = self.names_seen.get((parent_code, norm))
        if seen is not None:
            self.add(
                sheet,
                row,
                "Office Name" if sheet == OFFICE_SHEET else "Department Name (as on the site)",
                "possible_duplicate",
                ERROR,
                f"{SHEET_SHORT[seen[0]]} row {seen[1]} has the same name under the same parent",
                code,
            )
            ok = False
        else:
            self.names_seen[(parent_code, norm)] = (sheet, row)
        return ok

    def check_existing(
        self, sheet: str, row: int, code: str, existing: OfficeInfo, kind: str, parent_code: str, name: str
    ) -> tuple[bool, str | None]:
        ok = True
        if existing.kind != kind:
            self.add(
                sheet,
                row,
                "Code" if sheet == DEPT_SHEET else "Office Type",
                "kind_mismatch",
                ERROR,
                f"{code} exists as a {existing.kind}, not a {kind}; an office's type cannot change",
                code,
            )
            ok = False
        if existing.parent_code != parent_code:
            self.add(
                sheet,
                row,
                "Code",
                "parent_mismatch",
                ERROR,
                f"{code} exists under {existing.parent_code}, not under {parent_code}; an office cannot move",
                code,
            )
            ok = False
        if not existing.is_active:
            self.add(
                sheet,
                row,
                "Code",
                "office_inactive",
                ERROR,
                f"{code} is inactive; reactivate it in Administration first",
                code,
            )
            ok = False
        self.names_seen.setdefault((parent_code, normalised_name(existing.name)), (sheet, row))
        rename = None
        if ok and name and name != existing.name:
            rename = name[:200]
            self.add(
                sheet, row, None, "rename", NOTICE, f"{code} will be renamed to the workbook's name", code
            )
        return ok, rename

    # ------------------------------------------------------------------ people
    def designation(self, m: _Mention) -> tuple[str, str] | None:
        """(name, code) of the person's designation: an existing one matched by code or name, else a new one."""
        typed = clean(m.person.designation)
        key = _key(typed)
        for d in sorted(self.designations, key=lambda d: not d.is_active):
            if _key(d.code) == key or _key(d.name) == key:
                return d.name, d.code
        norm = " ".join(key.split())
        new = self.new_designations.get(norm)
        if new is None:
            code = designation_code_from_name(typed, self.taken_designation_codes)
            self.taken_designation_codes.add(code)
            new = NewDesignation(code=code, name=typed[:200])
            self.new_designations[norm] = new
            self.add(
                m.sheet,
                m.row,
                f"{m.label}: Designation",
                "designation_new",
                NOTICE,
                f'the designation "{new.name}" is not in ASLMS; it will be added with the code {new.code}',
                m.office_code,
            )
        return new.name, new.code

    def person(self, m: _Mention) -> PersonRef | None:
        """Checks one mention; the person's reference, or None when the mention has an error."""
        p, col = m.person, m.label
        if any(_placeholder(c) for c in p.cells()):
            self.add(
                m.sheet,
                m.row,
                col,
                "placeholder",
                ERROR,
                "the cells still hold the Read Me's example; fill in the real details",
                m.office_code,
            )
            return None
        email = p.email.strip().lower()
        if not email:
            self.add(
                m.sheet,
                m.row,
                f"{col}: Login E-mail",
                m.incomplete_code,
                ERROR,
                "the person's cells are partly filled: the login e-mail is missing",
                m.office_code,
            )
            return None
        if not EMAIL_RE.match(email) or " " in email:
            self.add(
                m.sheet,
                m.row,
                f"{col}: Login E-mail",
                "bad_email",
                ERROR,
                "not an e-mail address",
                m.office_code,
            )
            return None
        login = self.login(email)
        ok = True
        if login is not None and login.is_super_admin:
            self.add(
                m.sheet,
                m.row,
                f"{col}: Login E-mail",
                "super_admin_single",
                ERROR,
                f"{mask_address(email)} is the Super Administrator, who holds no other office",
                m.office_code,
            )
            return None
        if login is not None and not login.is_active:
            self.add(
                m.sheet,
                m.row,
                f"{col}: Login E-mail",
                "login_inactive",
                ERROR,
                f"the login {mask_address(email)} has its sign-in turned off",
                m.office_code,
            )
            ok = False
        has = _key(p.has_login)
        has_label = (
            "Already Has an ASLMS Login?"
            if m.label == "Office Head"
            else f"{col} Already Has an ASLMS Login?"
        )
        if has == "yes" and login is None:
            self.add(
                m.sheet,
                m.row,
                has_label,
                "login_missing",
                ERROR,
                f"the row says the person has a login, but there is no login {mask_address(email)}",
                m.office_code,
            )
            ok = False
        elif has == "no" and login is not None:
            self.add(
                m.sheet,
                m.row,
                has_label,
                "login_exists",
                NOTICE,
                f"the login {mask_address(email)} already exists; it will be used as it is",
                m.office_code,
            )
        missing = []
        if login is None and not p.full_name:
            missing.append("full name")
        if not p.designation:
            missing.append("designation")
        if missing:
            self.add(
                m.sheet,
                m.row,
                col,
                m.incomplete_code,
                ERROR,
                "the person's cells are partly filled: the " + " and the ".join(missing) + " missing",
                m.office_code,
            )
            ok = False
        if login is None and p.full_name and not (2 <= len(p.full_name) <= 200):
            self.add(
                m.sheet,
                m.row,
                f"{col}: Full Name",
                "bad_name",
                ERROR,
                "the full name must be 2 to 200 characters",
                m.office_code,
            )
            ok = False
        if login is None and p.mobile and _parse_mobile(p.mobile) is None:
            self.add(
                m.sheet,
                m.row,
                f"{col}: Mobile (10 digits)",
                "bad_mobile",
                ERROR,
                "the mobile number must be an Indian 10-digit number",
                m.office_code,
            )
            ok = False
        if not ok:
            return None
        self.mentions.setdefault(email, []).append(m)
        name, code = self.designation(m)
        return PersonRef(email=email, designation=name, designation_code=code, new_login=login is None)

    def plan_membership(
        self, ref: PersonRef, dept_code: str, office_code: str, role: str, m: _Mention
    ) -> bool:
        """The one-per-department rule for a new membership (decision 10): no other active membership of the login
        in the department, and no other planned one."""
        login = self.login(ref.email)
        clash = None
        if login is not None:
            for x in login.memberships:
                if x.department_code == dept_code and not (x.office_code == office_code and x.role == role):
                    clash = f"the login {mask_address(ref.email)} already holds a membership in {dept_code}"
        for email, d, _o, _r, other in self.planned:
            if email == ref.email and d == dept_code:
                clash = (
                    f"{SHEET_SHORT[other.sheet]} row {other.row} already names {mask_address(ref.email)} in "
                    f"{dept_code}"
                )
        if clash:
            self.add(
                m.sheet,
                m.row,
                f"{m.label}: Login E-mail",
                "one_per_department",
                ERROR,
                clash + "; a person holds one membership per department",
                m.office_code,
            )
            return False
        self.planned.append((ref.email, dept_code, office_code, role, m))
        return True

    def has_membership(self, email: str, office_code: str, role: str) -> bool:
        login = self.login(email)
        return login is not None and any(
            x.office_code == office_code and x.role == role for x in login.memberships
        )

    # ------------------------------------------------------------------ the sheets
    def departments(self) -> dict[str, tuple[str, str | None, str]]:
        """Checks the Departments sheet. Returns the parent index: a key (the row's name or code, normalised) ->
        (include state, code, kind)."""
        index: dict[str, tuple[str, str | None, str]] = {}
        for r in self.wb.departments:
            inc = _include(r.include)
            code_text = r.code.strip().upper() or None
            for k in (_key(r.name), _key(r.code)):
                if k:
                    index.setdefault(k, (inc, code_text, OfficeKind.DEPARTMENT.value))
            if inc == "no":
                self.add(
                    DEPT_SHEET, r.row, "Include?", "include_no", SKIP, "left out (Include? = No)", code_text
                )
                continue
            if inc == "wait":
                self.add(
                    DEPT_SHEET,
                    r.row,
                    "Include?",
                    "include_wait",
                    SKIP,
                    "waits for the owner (Include?)",
                    code_text,
                )
                continue
            self.department(r)
        return index

    def department(self, r: DeptRow) -> None:
        sheet = DEPT_SHEET
        if not r.name:
            self.add(sheet, r.row, "Department Name (as on the site)", "bad_name", ERROR, "the name is empty")
        code = self.check_code(sheet, r.row, r.code)
        if code is None or not r.name:
            return
        root = self.root.code
        existing = self.lk.office(code)
        if existing is not None:
            ok, rename = self.check_existing(
                sheet, r.row, code, existing, OfficeKind.DEPARTMENT.value, root, r.name
            )
            if not ok:
                return
            action = DeptAction(r.row, code, r.name[:200], r.website or None, "match", rename_to=rename)
        else:
            if not self.check_new_code(sheet, r.row, code, r.name, root):
                return
            if len(f"{self.root.path}/{code}") > MAX_PATH:
                self.add(
                    sheet,
                    r.row,
                    "Code",
                    "placement",
                    ERROR,
                    "the path would be longer than 400 characters",
                    code,
                )
                return
            action = DeptAction(r.row, code, r.name[:200], r.website or None, "create")
        head_ref = admin_ref = None
        head_m = _Mention(sheet, r.row, code, "Head", r.head, "head_partial")
        admin_m = _Mention(sheet, r.row, code, "Admin", r.admin, "person_incomplete")
        failed = False
        if not r.head.empty:
            head_ref = self.person(head_m)
            failed |= head_ref is None
        if not r.admin.empty:
            admin_ref = self.person(admin_m)
            failed |= admin_ref is None
        if head_ref and admin_ref and head_ref.email == admin_ref.email:
            self.add(
                sheet,
                r.row,
                "Admin: Login E-mail",
                "same_person_head_admin",
                ERROR,
                "the head and the administrator are the same person; a person holds one membership per department; "
                "name another administrator, or leave the Admin cells empty",
                code,
            )
            return
        # the head
        current_head = self.lk.head_email(code) if existing is not None else None
        if head_ref is None:
            if not failed and r.head.empty and current_head is None:
                self.add(
                    sheet,
                    r.row,
                    "Head",
                    "no_head_yet",
                    NOTICE,
                    "no head is named: the department "
                    + ("will be created" if existing is None else "stays")
                    + " with No Head Yet; name the head later by Head Change or a later run",
                    code,
                )
        elif existing is None:
            if self.plan_membership(head_ref, code, code, Role.DEPT_HEAD.value, head_m):
                action.head, action.head_action = head_ref, "create_with"
        elif current_head == head_ref.email:
            action.head, action.head_action = head_ref, "match"
        elif current_head is not None:
            self.add(
                sheet,
                r.row,
                "Head: Login E-mail",
                "head_differs",
                NOTICE,
                f"{code} already has another head; change it through Head Change",
                code,
            )
            action.head_action = "differs"
        elif self.plan_membership(head_ref, code, code, Role.DEPT_HEAD.value, head_m):
            action.head, action.head_action = head_ref, "set"
        # the admin
        current_admin = self.lk.admin_email(code) if existing is not None else None
        if admin_ref is None:
            if not failed and r.admin.empty and current_admin is None:
                self.add(
                    sheet, r.row, "Admin", "no_admin", NOTICE, "no Department Administrator is named", code
                )
        elif current_admin == admin_ref.email:
            action.admin, action.admin_action = admin_ref, "match"
        elif current_admin is not None:
            self.add(
                sheet,
                r.row,
                "Admin: Login E-mail",
                "admin_differs",
                NOTICE,
                f"{code} already has another Department Administrator; change it through the swap in Administration",
                code,
            )
            action.admin_action = "differs"
        elif self.plan_membership(admin_ref, code, code, Role.DEPT_ADMIN.value, admin_m):
            action.admin, action.admin_action = admin_ref, "add"
        self.plan.departments.append(action)

    def resolve_parent(
        self, r: OfficeRow, index: dict[str, tuple[str, str | None, str]]
    ) -> tuple[str, str | None, str | None, str | None]:
        """(state, code, kind, path) of the row's parent department: state is ok | left_out | waiting | unknown."""
        key = _key(r.parent)
        if key in index:
            inc, code, kind = index[key]
            if inc == "no":
                return "left_out", code, kind, None
            if inc == "wait":
                return "waiting", code, kind, None
            existing = self.lk.office(code) if code else None
            path = existing.path if existing is not None else f"{self.root.path}/{code}"
            return "ok", code, existing.kind if existing is not None else kind, path
        for d in self.lk.departments():
            if key in (_key(d.code), _key(d.name)):
                return "ok", d.code, d.kind, d.path
        return "unknown", None, None, None

    def office(self, r: OfficeRow, index: dict[str, tuple[str, str | None, str]]) -> None:
        sheet = OFFICE_SHEET
        code_text = r.code.strip().upper() or None
        inc = _include(r.include)
        if inc == "no":
            self.add(sheet, r.row, "Include?", "include_no", SKIP, "left out (Include? = No)", code_text)
            return
        if inc == "wait":
            self.add(
                sheet, r.row, "Include?", "include_wait", SKIP, "waits for the owner (Include?)", code_text
            )
            return
        state, parent_code, parent_kind, parent_path = self.resolve_parent(r, index)
        if state == "waiting":
            self.add(
                sheet,
                r.row,
                "Parent Department",
                "parent_waiting",
                SKIP,
                "waits with its parent department (To Decide)",
                code_text,
            )
            return
        if state == "left_out":
            self.add(
                sheet,
                r.row,
                "Parent Department",
                "parent_left_out",
                ERROR,
                "the parent department is left out (Include? = No) but this office says Yes",
                code_text,
            )
            return
        if state == "unknown" or parent_code is None:
            self.add(
                sheet,
                r.row,
                "Parent Department",
                "parent_unknown",
                ERROR,
                "the parent department is not on the Departments sheet and not in ASLMS",
                code_text,
            )
            return
        if not r.name:
            self.add(sheet, r.row, "Office Name", "bad_name", ERROR, "the name is empty", code_text)
        kind = self.kind_words.get(_key(r.kind))
        if kind is None or kind == OfficeKind.STATE:
            self.add(
                sheet, r.row, "Office Type", "kind_unknown", ERROR, "the office type is not known", code_text
            )
        code = self.check_code(sheet, r.row, r.code)
        if code is None or kind is None or kind == OfficeKind.STATE or not r.name:
            return
        if OfficeKind(parent_kind) not in PLACEMENT[kind]:
            self.add(
                sheet,
                r.row,
                "Office Type",
                "placement",
                ERROR,
                f"a {kind.value} cannot be placed under a {parent_kind} ({parent_code})",
                code,
            )
            return
        existing = self.lk.office(code)
        if existing is not None:
            ok, rename = self.check_existing(sheet, r.row, code, existing, kind.value, parent_code, r.name)
            if not ok:
                return
            action = OfficeAction(
                r.row,
                code,
                r.name[:200],
                r.website or None,
                kind.value,
                parent_code,
                "match",
                rename_to=rename,
            )
        else:
            if not self.check_new_code(sheet, r.row, code, r.name, parent_code):
                return
            if len(f"{parent_path}/{code}") > MAX_PATH:
                self.add(
                    sheet,
                    r.row,
                    "Code",
                    "placement",
                    ERROR,
                    "the path would be longer than 400 characters",
                    code,
                )
                return
            action = OfficeAction(
                r.row, code, r.name[:200], r.website or None, kind.value, parent_code, "create"
            )
        if not r.head.empty:
            m = _Mention(sheet, r.row, code, "Office Head", r.head, "person_incomplete")
            role = self.type_words.get(_key(r.head.user_type)) if r.head.user_type else None
            if not r.head.user_type or role is None:
                self.add(
                    sheet,
                    r.row,
                    "Office Head: User Type",
                    "type_unknown",
                    ERROR,
                    "the office head's user type is missing or not known (Directorate User or Department Officer)",
                    code,
                )
                self.person(m)
                return
            if role not in OFFICE_HEAD_TYPES:
                self.add(
                    sheet,
                    r.row,
                    "Office Head: User Type",
                    "type_not_allowed",
                    ERROR,
                    "an office head is a Directorate User or a Department Officer",
                    code,
                )
                self.person(m)
                return
            ref = self.person(m)
            if ref is None:
                return
            if existing is not None and self.has_membership(ref.email, code, role.value):
                action.head, action.head_role, action.head_action = ref, role.value, "match"
            elif self.plan_membership(ref, parent_code, code, role.value, m):
                action.head, action.head_role, action.head_action = ref, role.value, "add"
        self.plan.offices.append(action)

    # ------------------------------------------------------------------ the people across rows
    def people(self) -> None:
        for email, ms in self.mentions.items():
            login = self.login(email)
            names = {_key(m.person.full_name) for m in ms if m.person.full_name}
            mobiles = {_parse_mobile(m.person.mobile) for m in ms if m.person.mobile}
            if len(names) > 1 or len(mobiles) > 1:
                for m in ms[1:]:
                    self.add(
                        m.sheet,
                        m.row,
                        f"{m.label}: Login E-mail",
                        "person_conflict",
                        ERROR,
                        f"the rows naming {mask_address(email)} give different names or mobiles; give the same "
                        "details on every row",
                        m.office_code,
                    )
                continue
            if login is not None:
                self.plan.matched_logins.append(email)
                continue
            first = ms[0]
            mobile = next((_parse_mobile(m.person.mobile) for m in ms if m.person.mobile), None)
            if mobile is None:
                self.add(
                    first.sheet,
                    first.row,
                    f"{first.label}: Mobile (10 digits)",
                    "no_mobile",
                    NOTICE,
                    "no mobile number: the person gives it at the first sign-in",
                    first.office_code,
                )
            full_name = next(m.person.full_name for m in ms if m.person.full_name)
            self.plan.new_logins.append(NewLogin(email=email, full_name=full_name[:200], mobile=mobile))

    def run(self) -> ImportPlan:
        index = self.departments()
        for r in self.wb.offices:
            self.office(r, index)
        self.people()
        self.plan.new_designations = list(self.new_designations.values())
        return self.plan


def check_with(lookup: Lookup, wb: Workbook) -> ImportPlan:
    """Every check (decisions 9-13) against `lookup`; read-only."""
    return _Checker(lookup, wb).run()


def check(session: Session, wb: Workbook) -> ImportPlan:
    return check_with(DbLookup(session), wb)


# ------------------------------------------------------------------------------------------------ applying


@dataclass
class ImportResult:
    run_id: uuid.UUID
    plan: ImportPlan
    counts: dict[str, Any]
    created_codes: list[str] = field(default_factory=list)
    created_login_ids: list[uuid.UUID] = field(default_factory=list)
    summary_id: uuid.UUID | None = None
    welcome: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return self.summary_id is not None


def _notes(website: str | None) -> str:
    text = "From the Assam State Portal department list."
    return f"{text} Website: {website}" if website else text


def _designation_ids(session: Session) -> dict[str, uuid.UUID]:
    return {d.code: d.id for d in session.scalars(select(Designation)).all()}


def apply(
    session: Session,
    actor: Actor,
    actor_user: User,
    wb: Workbook,
    *,
    expect: str,
    run_id: uuid.UUID,
) -> ImportResult:
    """Applies the workbook in the caller's transaction (decision 14): the advisory lock, every check again, the
    fingerprint, then designations, logins, departments, admins, offices, office heads and the summary row. Raises
    `ImportErrors` or `PlanChanged` before any write. The caller commits."""
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": LOCK_KEY})
    plan = check(session, wb)
    if plan.errors:
        raise ImportErrors(plan)
    if fingerprint(wb.sha256, plan) != (expect or "").strip().lower():
        raise PlanChanged("the workbook or the database changed since the dry run; run the dry run again")
    result = ImportResult(run_id=run_id, plan=plan, counts=plan.counts())
    if not plan.has_changes:
        return result
    for nd in plan.new_designations:
        offices.create_designation(session, actor, actor_user, code=nd.code, name=nd.name)
    ids = _designation_ids(session)
    users: dict[str, User] = {}
    for nl in plan.new_logins:
        u = create_user(
            session,
            actor,
            email=nl.email,
            password=None,
            full_name=nl.full_name,
            role=None,
            office=None,
            mobile=nl.mobile,
        )
        users[nl.email] = u
        result.created_login_ids.append(u.id)
    for email in plan.matched_logins:
        users[email] = memberships.lookup(session, email)

    def head(ref: PersonRef) -> dict:
        return {
            "email": ref.email,
            "designation": ref.designation,
            "designation_id": ids[ref.designation_code],
        }

    root = memberships.state_root(session)
    for d in plan.departments:
        if d.action == "create":
            office = offices.create_office(
                session,
                actor,
                actor_user,
                code=d.code,
                name=d.name,
                kind=OfficeKind.DEPARTMENT,
                parent=root,
                notes=_notes(d.website),
                head=head(d.head) if d.head_action == "create_with" else None,
                allow_no_head=d.head_action != "create_with",
            )
            result.created_codes.append(office.code)
            continue
        office = offices.find_office(session, d.code)
        if d.rename_to:
            offices.update_office(session, actor, actor_user, office, name=d.rename_to)
        if d.head_action == "set":
            offices.set_missing_head(session, actor, actor_user, office, head(d.head))
    for d in plan.departments:
        if d.admin_action == "add":
            ref = d.admin
            offices.add_department_admin(
                session,
                actor,
                actor_user,
                offices.find_office(session, d.code),
                user=users[ref.email],
                designation=ref.designation,
                designation_id=ids[ref.designation_code],
            )
    for o in plan.offices:
        if o.action == "create":
            office = offices.create_office(
                session,
                actor,
                actor_user,
                code=o.code,
                name=o.name,
                kind=o.kind,
                parent=offices.find_office(session, o.parent_code),
                notes=_notes(o.website),
            )
            result.created_codes.append(office.code)
        elif o.rename_to:
            offices.update_office(
                session, actor, actor_user, offices.find_office(session, o.code), name=o.rename_to
            )
    for o in plan.offices:
        if o.head_action == "add":
            ref = o.head
            memberships.add(
                session,
                actor,
                actor_user,
                users[ref.email],
                office=offices.find_office(session, o.code),
                role=Role(o.head_role),
                designation=ref.designation,
                designation_id=ids[ref.designation_code],
            )
    row = write_audit(
        session,
        actor,
        "office_import.applied",
        "office_import",
        run_id,
        row_id=run_id,
        after={
            "file_sha256": wb.sha256,
            "fingerprint": expect.strip().lower(),
            "counts": result.counts,
            "codes_created": result.created_codes,
            "logins_created": [str(i) for i in result.created_login_ids],
        },
    )
    result.summary_id = row.id
    session.flush()
    return result


def import_actor(session: Session, run_id: uuid.UUID) -> tuple[Actor, User]:
    """The single active Super Administrator, with the run's user agent on every audit row (decision 19)."""
    current = memberships.super_admin_membership(session)
    user = session.get(User, current.user_id) if current is not None else None
    if user is None or not user.is_active:
        raise NoSuperAdmin(
            "there is no active Super Administrator; run `aslms users create-super-admin` first"
        )
    return access.actor_for(user, user_agent=f"{USER_AGENT} {run_id}"), user


def run_apply(
    session_factory: sessionmaker[Session],
    wb: Workbook,
    *,
    expect: str,
    run_id: uuid.UUID,
    mailer=None,
    settings=None,
) -> ImportResult:
    """`apply` in a transaction of its own, committed; then one welcome mail per new login (decision 18), each
    audited apart. With `mailer=None` no mail is sent (`--no-welcome`)."""
    from aslms.services.users import send_welcome

    with session_factory() as s:
        try:
            actor, actor_user = import_actor(s, run_id)
            result = apply(s, actor, actor_user, wb, expect=expect, run_id=run_id)
            s.commit()
        except Exception:
            s.rollback()
            raise
    if mailer is None or not result.created_login_ids:
        return result
    sent = failed = 0
    with session_factory() as s:
        users = [s.get(User, i) for i in result.created_login_ids]
    for u in users:
        if send_welcome(session_factory, mailer, settings, u, actor=actor):
            sent += 1
        else:
            failed += 1
    result.welcome = {"sent": sent, "failed": failed}
    return result
