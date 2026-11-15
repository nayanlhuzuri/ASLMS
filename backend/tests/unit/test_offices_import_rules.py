"""The import's checks against a faked lookup (design `offices-import`, decisions 6 and 9-13): the code pattern and the
17-character limit, duplicate codes across the sheets, placeholders, one e-mail with different names, a partly filled
head, Include? = No / To Decide, an office under a left-out department, the user type words, designation codes from
names and the name normalising of the duplicate check. Design `offices-import-followups`: codes checked on every row
whatever its Include? says, designations turned off refused for a new membership, names over 200 characters refused."""

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
    extra_designations: list[imp.DesignationInfo] = field(default_factory=list)

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
            *self.extra_designations,
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


# ------------------------------------------------------------------------------------------------ offices-import-followups


def _dup(plan):
    return [p for p in plan.problems if p.code == "duplicate_code_in_file"]


def test_code_shared_by_left_out_row_and_included_row_is_error():
    # skipped first, included later, across the sheets: Departments "No" and Offices "Yes"
    plan = _plan(
        [dept("Transport", "TRANS", **H), dept("Health", "HFW-X", include="No")],
        [office("Transport", "Health Board", "Board / Corporation", "HFW-X")],
    )
    dup = _dup(plan)
    assert [(p.sheet, p.row, p.severity) for p in dup] == [(imp.DEPT_SHEET, 6, "error")]
    assert "Offices row 5 (included)" in dup[0].message and "even one left out" in dup[0].message
    assert [o.code for o in plan.offices] == ["HFW-X"] and plan.errors
    assert "include_no" in _codes(plan, "skip")
    # included first, skipped later, across the sheets: Departments "Yes" and Offices "No"
    plan = _plan(
        [dept("Transport", "TRANS", **H)],
        [office("Transport", "Transport Board", "Board / Corporation", "TRANS", include="No")],
    )
    dup = _dup(plan)
    assert [(p.sheet, p.row) for p in dup] == [(imp.OFFICE_SHEET, 5)]
    assert "Departments row 5 (included)" in dup[0].message
    assert [d.code for d in plan.departments] == ["TRANS"] and plan.errors
    # the same sheet: two department rows, the left-out one first
    plan = _plan([dept("Health Old", "HEALTH", include="No"), dept("Health", "HEALTH", **H)])
    assert [(p.sheet, p.row) for p in _dup(plan)] == [(imp.DEPT_SHEET, 5)]
    assert [d.code for d in plan.departments] == ["HEALTH"]
    # the same sheet: two office rows, the included one first
    plan = _plan(
        [dept("Transport", "TRANS", **H)],
        [
            office("Transport", "Board One", "Board / Corporation", "TRANS-B1"),
            office("Transport", "Board Two", "Board / Corporation", "TRANS-B1", include="No"),
        ],
    )
    assert [(p.sheet, p.row) for p in _dup(plan)] == [(imp.OFFICE_SHEET, 6)]
    assert [o.code for o in plan.offices] == ["TRANS-B1"]


def test_code_shared_by_waiting_row_and_included_row_is_error():
    for include in ("To Decide", ""):
        plan = _plan(
            [dept("Transport", "TRANS", **H), dept("Tourism", "TOURISM", include=include)],
            [office("Transport", "Tourism Board", "Board / Corporation", "TOURISM")],
        )
        dup = _dup(plan)
        assert [(p.sheet, p.row) for p in dup] == [(imp.DEPT_SHEET, 6)], include
        assert "even one waiting" in dup[0].message
        assert "include_wait" in _codes(plan, "skip")
        assert [o.code for o in plan.offices] == ["TOURISM"]


def test_code_shared_by_two_included_rows_still_error_on_later_row():
    plan = _plan([dept("Transport", "TRANS", **H), dept("Tourism", "TRANS")])
    dup = _dup(plan)
    assert [(p.sheet, p.row) for p in dup] == [(imp.DEPT_SHEET, 6)]
    assert "Departments row 5 (included)" in dup[0].message
    assert [d.code for d in plan.departments] == ["TRANS"]


def test_code_shared_only_by_skipped_rows_not_reported():
    plan = _plan(
        [dept("Transport", "TRANS", **H), dept("Tourism", "TOURISM", include="No")],
        [office("Transport", "Tourism Board", "Board / Corporation", "TOURISM", include="To Decide")],
    )
    assert not plan.errors
    assert _codes(plan, "skip") == ["include_no", "include_wait"]


def test_malformed_code_reported_once():
    plan = _plan([dept("Transport", "TR ANS", **H), dept("Tourism", "TR ANS", include="No")])
    assert _codes(plan, "error") == ["bad_code"]


def test_inactive_designation_refused_for_new_membership():
    lookup = FakeLookup(extra_designations=[imp.DesignationInfo("MD", "Managing Director", False)])
    plan = _plan(
        [
            dept(
                "Transport",
                "TRANS",
                **head("Asha Das", "asha@example.gov.in", designation="Managing Director"),
                **admin("Bina Roy", "bina@example.gov.in", designation="md"),
            )
        ],
        [
            office(
                "Transport",
                "Transport Board",
                "Board / Corporation",
                "TRANS-B1",
                **office_head("Chandan Bora", "chandan@example.gov.in", designation="Managing Director"),
            )
        ],
        lookup=lookup,
    )
    inactive = [p for p in plan.errors if p.code == "designation_inactive"]
    assert [p.column for p in inactive] == [
        "Head: Designation",
        "Admin: Designation",
        "Office Head: Designation",
    ]
    assert '"Managing Director" (MD) is turned off' in inactive[0].message
    assert plan.new_designations == [] and "designation_new" not in _codes(plan)
    assert plan.departments[0].head_action == "none" and plan.departments[0].admin_action == "none"
    assert plan.offices[0].head_action == "none"
    # an existing department with no head: a head `set` is refused the same way
    lookup.offices["HEALTH"] = imp.OfficeInfo("HEALTH", "Health", "department", "GOA/HEALTH", "GOA", True)
    plan = _plan(
        [dept("Health", "HEALTH", **head("Asha Das", "asha@example.gov.in", designation="MD"))], lookup=lookup
    )
    assert _codes(plan, "error") == ["designation_inactive"]


def test_active_designation_preferred_over_inactive():
    lookup = FakeLookup(
        extra_designations=[
            imp.DesignationInfo("COMMISSIONER", "Commissioner (Old)", False),
            imp.DesignationInfo("COMMR", "Commissioner", True),
        ]
    )
    plan = _plan(
        [dept("Transport", "TRANS", **head("Asha Das", "asha@example.gov.in", designation="Commissioner"))],
        lookup=lookup,
    )
    assert not plan.errors and plan.new_designations == []
    assert plan.departments[0].head.designation_code == "COMMR"
    assert plan.departments[0].head_action == "create_with"


def test_inactive_designation_ignored_for_matched_membership():
    lookup = FakeLookup(extra_designations=[imp.DesignationInfo("MD", "Managing Director", False)])
    lookup.offices["TRANS"] = imp.OfficeInfo("TRANS", "Transport", "department", "GOA/TRANS", "GOA", True)
    lookup.offices["TRANS-B1"] = imp.OfficeInfo(
        "TRANS-B1", "Transport Board", "board_corporation", "GOA/TRANS/TRANS-B1", "TRANS", True
    )
    lookup.heads["TRANS"] = "asha@example.gov.in"
    lookup.admins["TRANS"] = "bina@example.gov.in"
    lookup.logins["asha@example.gov.in"] = imp.LoginInfo(
        "asha@example.gov.in", True, False, (imp.MemberInfo("TRANS", "TRANS", "dept_head"),)
    )
    lookup.logins["bina@example.gov.in"] = imp.LoginInfo(
        "bina@example.gov.in", True, False, (imp.MemberInfo("TRANS", "TRANS", "dept_admin"),)
    )
    lookup.logins["chandan@example.gov.in"] = imp.LoginInfo(
        "chandan@example.gov.in", True, False, (imp.MemberInfo("TRANS-B1", "TRANS", "directorate_user"),)
    )
    plan = _plan(
        [
            dept(
                "Transport",
                "TRANS",
                **head("Asha Das", "asha@example.gov.in", designation="Managing Director"),
                **admin("Bina Roy", "bina@example.gov.in", designation="MD"),
            )
        ],
        [
            office(
                "Transport",
                "Transport Board",
                "Board / Corporation",
                "TRANS-B1",
                **office_head("Chandan Bora", "chandan@example.gov.in", designation="MD"),
            )
        ],
        lookup=lookup,
    )
    assert not plan.errors, [p.code for p in plan.errors]
    assert plan.departments[0].head_action == "match" and plan.departments[0].admin_action == "match"
    assert plan.offices[0].head_action == "match"
    assert not plan.has_changes


def test_office_name_over_200_is_error():
    long = "A" * 199 + " B"  # 201 characters
    plan = _plan(
        [dept("Transport", "TRANS", **H), dept(long, "TOURISM")],
        [
            office("Transport", long, "Board / Corporation", "TRANS-B1"),
            office("Transport", "Transport Board", "Board / Corporation", "TRANS-B2"),
        ],
    )
    bad = [p for p in plan.errors if p.code == "bad_name"]
    assert [(p.sheet, p.row, p.column) for p in bad] == [
        (imp.DEPT_SHEET, 6, "Department Name (as on the site)"),
        (imp.OFFICE_SHEET, 5, "Office Name"),
    ]
    assert "201 characters" in bad[0].message and "at most 200" in bad[0].message
    assert [d.code for d in plan.departments] == ["TRANS"]
    assert [o.code for o in plan.offices] == ["TRANS-B2"]
    # an existing office renamed to a name over 200 characters is refused, not cut
    lookup = FakeLookup()
    lookup.offices["HEALTH"] = imp.OfficeInfo("HEALTH", "Health", "department", "GOA/HEALTH", "GOA", True)
    plan = _plan([dept(long, "HEALTH")], lookup=lookup)
    assert _codes(plan, "error") == ["bad_name"] and plan.departments == []


def test_name_of_exactly_200_accepted():
    name = "A" * 198 + " B"  # 200 characters
    plan = _plan(
        [dept(name, "TRANS", **H)],
        [office(name, name, "Board / Corporation", "TRANS-B1")],
    )
    assert not plan.errors
    assert plan.departments[0].name == name and plan.offices[0].name == name
    lookup = FakeLookup()
    lookup.offices["HEALTH"] = imp.OfficeInfo("HEALTH", "Health", "department", "GOA/HEALTH", "GOA", True)
    plan = _plan([dept(name, "HEALTH")], lookup=lookup)
    assert not plan.errors and plan.departments[0].rename_to == name


def test_designation_over_200_is_error_and_not_planned():
    long = "Additional " * 19 + "Director"  # 217 characters
    assert len(long) > 200
    plan = _plan(
        [
            dept("Transport", "TRANS", **head("Asha Das", "asha@example.gov.in", designation=long)),
            dept("Tourism", "TOURISM", **head("Bina Roy", "bina@example.gov.in", designation="A" * 200)),
        ]
    )
    bad = [p for p in plan.errors if p.code == "bad_designation"]
    assert [(p.row, p.column) for p in bad] == [(5, "Head: Designation")]
    assert f"{len(long)} characters" in bad[0].message and "at most 200" in bad[0].message
    assert [d.name for d in plan.new_designations] == ["A" * 200]
    assert plan.departments[0].head is None and plan.departments[0].head_action == "none"
    assert [n.email for n in plan.new_logins] == ["bina@example.gov.in"]
