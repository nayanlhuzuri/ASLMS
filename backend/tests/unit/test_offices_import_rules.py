"""The import's checks against a faked lookup (design `offices-import`, decisions 6 and 9-13): the code pattern and the
17-character limit, duplicate codes across the sheets, placeholders, one e-mail with different names, a partly filled
head, Include? = No / To Decide, an office under a left-out department, the user type words, designation codes from
names and the name normalising of the duplicate check."""

from __future__ import annotations

from dataclasses import dataclass, field

from aslms.services import offices_import as imp
from aslms.services.offices import designation_code_from_name, normalised_name
from tests.offices_workbook import admin, build, dept, head, office, office_head


@dataclass
class FakeLookup:
    offices: dict[str, imp.OfficeInfo] = field(default_factory=dict)
    logins: dict[str, imp.LoginInfo] = field(default_factory=dict)
    heads: dict[str, str] = field(default_factory=dict)
    admins: dict[str, str] = field(default_factory=dict)
    courts: set[str] = field(default_factory=lambda: {"GHC"})

    def __post_init__(self) -> None:
        self.offices.setdefault(
            "GOA", imp.OfficeInfo("GOA", "Government of Assam", "state", "GOA", None, True)
        )

    def root(self):
        return self.offices["GOA"]

    def office(self, code):
        return self.offices.get(code.upper())

    def children(self, parent_code):
        return [o for o in self.offices.values() if o.parent_code == parent_code and o.is_active]

    def departments(self):
        return [o for o in self.offices.values() if o.kind == "department" and o.path.count("/") == 1]

    def court_code(self, code):
        return code in self.courts

    def login(self, email):
        return self.logins.get(email)

    def designations(self):
        return [
            imp.DesignationInfo("SECY", "Secretary", True),
            imp.DesignationInfo("DY_SECY", "Deputy Secretary", True),
            imp.DesignationInfo("DIRECTOR", "Director", True),
        ]

    def role_labels(self):
        return {
            "dept_officer": "Department Officer",
            "directorate_user": "Directorate Officer",
            "auditor": "Auditor",
        }

    def kind_labels(self):
        return {
            "department": "Department",
            "directorate": "Directorate / Commissionerate",
            "board_corporation": "Board / Corporation",
            "unit": "Unit",
        }

    def head_email(self, code):
        return self.heads.get(code)

    def admin_email(self, code):
        return self.admins.get(code)


def _plan(departments, offices=None, lookup=None):
    return imp.check_with(lookup or FakeLookup(), imp.read_workbook(build(departments, offices)))


def _codes(plan, severity=None):
    return [p.code for p in plan.problems if severity is None or p.severity == severity]


H = head("Asha Das", "asha@example.gov.in", mobile="9864012345")


def test_code_pattern_and_17_char_limit():
    plan = _plan(
        [
            dept("Transport", "TRANS", **H),
            dept("Tourism", "ABCDEFGHIJKLMNOPQR", **head("Bina Roy", "bina@example.gov.in")),  # 18
            dept("Sports", "SP ORTS", **head("Chandan Bora", "chandan@example.gov.in")),
            dept("Soil", "ABCDEFGHIJKLMNOPQ", **head("Dipa Nath", "dipa@example.gov.in")),  # 17, fine
        ]
    )
    assert _codes(plan, "error") == ["code_too_long", "bad_code"]
    assert {d.code for d in plan.departments} == {"TRANS", "ABCDEFGHIJKLMNOPQ"}
    too_long = next(p for p in plan.errors if p.code == "code_too_long")
    assert "17" in too_long.message and too_long.row == 6


def test_duplicate_code_across_sheets():
    plan = _plan(
        [dept("Transport", "TRANS", **H)],
        [office("Transport", "Transport Board", "Board / Corporation", "TRANS")],
    )
    dup = [p for p in plan.errors if p.code == "duplicate_code_in_file"]
    assert len(dup) == 1 and dup[0].sheet == imp.OFFICE_SHEET and "Departments row 5" in dup[0].message


def test_placeholder_values_refused():
    plan = _plan(
        [
            dept("Transport", "TRANS", **head("[Head's Full Name]", "[name]@assam.gov.in")),
            dept("Tourism", "TOURISM", **head("Bina Roy", "bina@example.gov.in", mobile="9XXXXXXXXX")),
        ]
    )
    assert _codes(plan, "error") == ["placeholder", "placeholder"]


def test_same_email_different_name_is_error():
    plan = _plan(
        [
            dept("Transport", "TRANS", **head("Asha Das", "asha@example.gov.in")),
            dept("Tourism", "TOURISM", **head("Asha Devi", "ASHA@example.gov.in")),
        ]
    )
    conflict = [p for p in plan.errors if p.code == "person_conflict"]
    assert len(conflict) == 1 and conflict[0].row == 6
    assert "Asha" not in conflict[0].message and "a***@example.gov.in" in conflict[0].message
    # the same person heading two departments with the same details is one login
    plan = _plan(
        [
            dept("Transport", "TRANS", **head("Asha Das", "asha@example.gov.in")),
            dept("Tourism", "TOURISM", **head("Asha  Das", "asha@example.gov.in")),
        ]
    )
    assert not plan.errors and [n.email for n in plan.new_logins] == ["asha@example.gov.in"]


def test_partial_head_is_error():
    partial = {"head_name": "Asha Das", "head_designation": "Secretary"}  # no e-mail
    plan = _plan([dept("Transport", "TRANS", **partial)])
    assert _codes(plan, "error") == ["head_partial"]
    plan = _plan([dept("Transport", "TRANS", head_email="asha@example.gov.in", head_designation="Secretary")])
    assert _codes(plan, "error") == ["head_partial"]  # a new login needs the full name
    # all five head cells empty: a department with No Head Yet (a notice)
    plan = _plan([dept("Transport", "TRANS")])
    assert not plan.errors and "no_head_yet" in _codes(plan, "notice")
    assert plan.departments[0].head_action == "none"
    assert plan.counts()["departments_no_head_yet"] == 1


def test_include_no_and_to_decide_skip():
    plan = _plan(
        [
            dept("Transport", "TRANS", **H),
            dept("Tourism", "TOURISM", include="No"),
            dept("Sports", "SPORTS", include="To Decide"),
            dept("Soil", "SOIL", include=""),
        ],
        [office("Sports", "Sports Authority", "Statutory Authority / Commission", "SPORTS-SA")],
    )
    assert _codes(plan, "skip") == ["include_no", "include_wait", "include_wait", "parent_waiting"]
    assert [d.code for d in plan.departments] == ["TRANS"]
    assert plan.offices == []
    assert plan.counts()["rows_skipped"] == {"include_no": 1, "include_wait": 2, "parent_waiting": 1}


def test_office_under_left_out_department_is_error():
    plan = _plan(
        [dept("Transport", "TRANS", **H), dept("Tourism", "TOURISM", include="No")],
        [office("Tourism", "Tourism Corporation", "Board / Corporation", "TOURISM-CORP")],
    )
    assert _codes(plan, "error") == ["parent_left_out"]


def test_user_type_aliases():
    rows = [
        office(
            "Transport",
            f"Office {i}",
            "Unit",
            f"TRANS-U{i}",
            **office_head(f"Person {i}", f"p{i}@example.gov.in", user_type=t),
        )
        for i, t in enumerate(
            ["Directorate User", "directorate_user", "Directorate Officer", "Department Officer"]
        )
    ]
    plan = _plan([dept("Transport", "TRANS", **H)], rows)
    assert not plan.errors
    assert [o.head_role for o in plan.offices] == ["directorate_user"] * 3 + ["dept_officer"]
    bad = [
        office(
            "Transport",
            "Office A",
            "Unit",
            "TRANS-UA",
            **office_head("Person A", "a@example.gov.in", "Auditor"),
        ),
        office(
            "Transport",
            "Office B",
            "Unit",
            "TRANS-UB",
            **office_head("Person B", "b@example.gov.in", "Clerk"),
        ),
        office(
            "Transport", "Office C", "Unit", "TRANS-UC", **office_head("Person C", "c@example.gov.in", "")
        ),
    ]
    plan = _plan([dept("Transport", "TRANS", **H)], bad)
    assert _codes(plan, "error") == ["type_not_allowed", "type_unknown", "type_unknown"]


def test_designation_code_from_name():
    assert designation_code_from_name("Joint Director & Head", set()) == "JOINT_DIRECTOR_AND_HEAD"
    assert (
        designation_code_from_name("Commissioner (Excise)", {"COMMISSIONER_EXCISE"})
        == "COMMISSIONER_EXCISE_2"
    )
    taken = {"COMMISSIONER_EXCISE", "COMMISSIONER_EXCISE_2"}
    assert designation_code_from_name("commissioner excise", taken) == "COMMISSIONER_EXCISE_3"
    long = designation_code_from_name("A" * 60, set())
    assert len(long) == 40
    assert len(designation_code_from_name("A" * 60, {long})) <= 40
    # a new designation is planned once, with its code, and named in a notice
    plan = _plan(
        [
            dept(
                "Transport",
                "TRANS",
                **head("Asha Das", "asha@example.gov.in", designation="Mission Director"),
            ),
            dept(
                "Tourism",
                "TOURISM",
                **head("Bina Roy", "bina@example.gov.in", designation="mission  director"),
            ),
        ]
    )
    assert [(d.code, d.name) for d in plan.new_designations] == [("MISSION_DIRECTOR", "Mission Director")]
    assert _codes(plan, "notice").count("designation_new") == 1
    # an existing designation is matched by code or by name, whatever the case
    plan = _plan([dept("Transport", "TRANS", **head("Asha Das", "asha@example.gov.in", designation="secy"))])
    assert plan.new_designations == [] and plan.departments[0].head.designation == "Secretary"


def test_normalised_name():
    assert normalised_name("Department of School Education") == "school education"
    assert normalised_name("School Education") == "school education"
    assert normalised_name("Information Technology Department") == "information technology"
    assert normalised_name("Sports & Youth Welfare") == normalised_name("Sports and Youth Welfare")
    assert normalised_name("Tribal Affairs (Plain)") == "tribal affairs plain"


def test_possible_duplicate_and_existing_matches():
    lookup = FakeLookup()
    lookup.offices["SEC-EDU"] = imp.OfficeInfo(
        "SEC-EDU", "Department of School Education", "department", "GOA/SEC-EDU", "GOA", True
    )
    lookup.heads["SEC-EDU"] = "head@example.gov.in"
    plan = _plan([dept("School Education", "SCH-EDU", **H)], lookup=lookup)
    dup = [p for p in plan.errors if p.code == "possible_duplicate"]
    assert len(dup) == 1 and "SEC-EDU" in dup[0].message
    plan = _plan([dept("School Education", "SEC-EDU", **H)], lookup=lookup)
    assert not plan.errors
    assert plan.departments[0].action == "match" and plan.departments[0].rename_to == "School Education"
    assert set(_codes(plan, "notice")) >= {"rename", "head_differs"}


def test_head_and_admin_same_person_and_login_cross_checks():
    plan = _plan([dept("Transport", "TRANS", **H, **admin("Asha Das", "asha@example.gov.in"))])
    assert _codes(plan, "error") == ["same_person_head_admin"]
    lookup = FakeLookup()
    lookup.logins["old@example.gov.in"] = imp.LoginInfo("old@example.gov.in", True, False)
    lookup.logins["root@example.gov.in"] = imp.LoginInfo("root@example.gov.in", True, True)
    plan = _plan(
        [
            dept("Transport", "TRANS", **head("Asha Das", "asha@example.gov.in", has_login="Yes")),
            dept("Tourism", "TOURISM", **head("", "old@example.gov.in", has_login="No")),
            dept("Sports", "SPORTS", **head("Root", "root@example.gov.in")),
        ],
        lookup=lookup,
    )
    assert _codes(plan, "error") == ["login_missing", "super_admin_single"]
    assert "login_exists" in _codes(plan, "notice")
    assert plan.matched_logins == ["old@example.gov.in"]


def test_problem_output_has_no_names_or_mobiles():
    plan = _plan(
        [
            dept("Transport", "TRANS", **head("Asha Das", "asha@example.gov.in", mobile="12345")),
            dept("Tourism", "TOURISM", **head("Asha Devi", "asha@example.gov.in", mobile="9864012345")),
        ]
    )
    text = " ".join(p.where() + p.message for p in plan.problems)
    assert "Asha" not in text and "12345" not in text and "9864012345" not in text
    assert "asha@example.gov.in" not in text
